import pyglet
import time
from pyglet import clock
from pyglet.window import key
from config import *
from utils import *
from image_processor import (
    image_cache, apply_sharpening, clean_cache, 
    generate_thumbnail_page, create_thumbnail_sprite_from_data,
    thumbnail_data_cache, thumbnail_cache, cleanup_thumbnails
)

class SlideShow:
    def __init__(self, images, window):
        self.images = images  # 保存图片列表
        self.window = window  # 保存窗口引用
        self.batch = pyglet.graphics.Batch()
        self.current = None
        self.next_img = None
        self.transitioning = False
        self.old_img = None
        self.animation_start_time = 0
        self.manual_mode = False
        self.current_index = 0
        self.thumbnail_mode = False
        self.thumbnail_page = 0
        self.progress_bg_color = (11, 11, 11, 255)
        self.progress_fg_color = (102, 102, 102, 255)
        self.progress_bg = pyglet.shapes.Rectangle(0, 0, 0, 0, color=(0,0,0))
        self.progress_fg = pyglet.shapes.Rectangle(0, 0, 0, 0, color=(0,0,0))
        self.progress_bg.visible = False
        self.progress_fg.visible = False

    def update_progress(self, progress):
        if self.manual_mode or self.thumbnail_mode or not self.images:
            self.progress_bg.visible = False
            self.progress_fg.visible = False
            return

        total_width = self.window.width
        bar_width = total_width * progress

        self.progress_bg.width = total_width
        self.progress_bg.height = PROGRESS_BAR_HEIGHT
        self.progress_bg.color = self.progress_bg_color[:3]
        self.progress_bg.opacity = self.progress_bg_color[3]

        self.progress_fg.width = bar_width
        self.progress_fg.height = PROGRESS_BAR_HEIGHT
        self.progress_fg.color = self.progress_fg_color[:3]
        self.progress_fg.opacity = self.progress_fg_color[3]

        self.progress_bg.visible = True
        self.progress_fg.visible = True

    def draw_sigle_pic(self, path, add_to_batch=True):
        debug_gc_collect("draw_sigle_pic")
        if path not in image_cache:
            try:
                # 应用锐化效果后加载图片，传入窗口尺寸
                img = apply_sharpening(path, self.window.width, self.window.height)
                image_cache[path] = img
            except Exception as e:
                print(f"加载图片失败: {path} - {e}")
                return None
        else:
            image_cache.move_to_end(path)
        
        clean_cache()
        sprite = None
      
        try:
            sprite = pyglet.sprite.Sprite(image_cache[path], batch=self.batch if add_to_batch else None)
            self.center_sprite(sprite, self.window.width, self.window.height)
            self.window.set_caption(os.path.basename(path))
            return sprite
        except Exception as e:
            print(f"创建精灵失败: {e}")
            return None

    def _position_thumbnail(self, sprite, start_index, idx):
        """ 定位缩略图位置 """
        # 在计算缩放前添加安全检查
        if sprite.width == 0 or sprite.height == 0:
            return
        padding = 10
        columns = 5
        rows = 2
        cell_width = (self.window.width - (columns + 1) * padding) / columns
        cell_height = (self.window.height - (rows + 1) * padding) / rows

        pos_in_page = idx - start_index
        col = pos_in_page % columns
        row = pos_in_page // columns
        cell_x = padding + col * (cell_width + padding)
        cell_y = self.window.height - padding - (row + 1) * cell_height - row * padding

        scale_w = cell_width / sprite.width
        scale_h = cell_height / sprite.height
        scale_factor = min(scale_w, scale_h)
        sprite.update(scale=scale_factor)
        sprite.x = cell_x + (cell_width - sprite.width) / 2
        sprite.y = cell_y + (cell_height - sprite.height) / 2

    def draw_thumbnails(self):
        """绘制缩略图页面"""
        # 使用 image_processor 中的函数生成缩略图页面
        def thumbnail_ready_callback(future, page_start, idx_in_page):
            try:
                result = future.result()
                path, image_data, size = result
                
                def update_thumbnail(dt):
                    # 更新缩略图数据缓存
                    thumbnail_data_cache[path] = result
                    
                    # 创建精灵并定位
                    sprite = create_thumbnail_sprite_from_data(result)
                    if sprite:
                        self._position_thumbnail(sprite, page_start, idx_in_page)
                        
                        # 更新缓存中的精灵
                        page_key = (page_start, self.window.width, self.window.height)
                        if page_key in thumbnail_cache:
                            thumbnail_cache[page_key][idx_in_page - page_start] = sprite
                
                pyglet.clock.schedule_once(update_thumbnail, 0)
            except Exception as e:
                print(f"处理缩略图回调时出错: {e}")

        # 生成缩略图页面
        sprites = generate_thumbnail_page(
            self.images, 
            self.thumbnail_page, 
            self.window.width, 
            self.window.height,
            thumbnail_ready_callback
        )
        
        # 绘制所有精灵
        for sprite in sprites:
            if sprite:
                sprite.draw()

    def scale_to_fit(self, sprite, max_width, max_height):
        if sprite.image:
            original_width = sprite.image.width
            original_height = sprite.image.height
            scale = min(max_width / original_width, max_height / original_height)
            sprite.scale = scale

    def center_sprite(self, sprite, max_width, max_height):
        sprite.x = (max_width - sprite.width) // 2
        sprite.y = (max_height - sprite.height) // 2

    def _safe_delete_sprite(self, sprite, sprite_name="精灵"):
        """安全删除精灵的辅助函数"""
        # print(f"DEBUG: 清理{sprite_name}前 - 类型: {type(sprite)}, 值: {sprite}")
        if sprite:
            try:
                # 更安全的删除方式：先移除batch，再删除
                if hasattr(sprite, 'batch') and sprite.batch:
                    sprite.batch = None
                if hasattr(sprite, 'delete'):
                    sprite.delete()
                # print(f"DEBUG: {sprite_name}删除后 - 类型: {type(sprite)}, 值: {sprite}")
                # print(f"DEBUG: {sprite_name}删除成功")
                # 返回None表示已删除
                return None
            except Exception as e:
                print(f"清理{sprite_name}出错: {e}")
                return sprite
        else:
            print(f"DEBUG: 跳过删除 - {sprite_name}不存在")
            return None

    def load_next(self):
        if not self.images:
            return
        next_index = (self.current_index + 1) % len(self.images)
        path = self.images[next_index]
        self.next_img = self.draw_sigle_pic(path)
        self.current_index = next_index

    def transition(self, dt):
        if self.manual_mode or self.transitioning or not self.next_img:
            return
        self.transitioning = True
        self.animation_start_time = time.time()
        if self.current:
            # 创建一个新的精灵对象，而不是共享引用
            self.old_img = pyglet.sprite.Sprite(self.current.image, batch=self.batch)
            self.old_img.x = self.current.x
            self.old_img.y = self.current.y
            self.old_img.scale = self.current.scale
            self.old_img.opacity = 255
        self.next_img.x = self.window.width
        clock.schedule_interval(self.slide_left, 1/60)
        clock.schedule_interval(self.fade_out_old, 1/60)

    def slide_left(self, dt):
        elapsed = time.time() - self.animation_start_time
        progress = min(elapsed / TRANSITION, 1.0)
        eased_progress = ease_out_quad(progress)
        target_x = (self.window.width - self.next_img.width) // 2
        self.next_img.x = self.window.width - (self.window.width - target_x) * eased_progress
        if progress >= 1.0:
            clock.unschedule(self.slide_left)
            
            # 删除旧的当前精灵
            self.current = self._safe_delete_sprite(self.current, "当前精灵")
            
            self.current = self.next_img
            self.next_img = None
            self.transitioning = False
            
            # 清理旧的动画精灵
            self.old_img = self._safe_delete_sprite(self.old_img, "旧精灵")
            self.old_img = None

    def fade_out_old(self, dt):
        if self.old_img and hasattr(self.old_img, 'opacity'):
            elapsed = time.time() - self.animation_start_time
            # 加速消失 用/4加速
            progress = min(elapsed / (TRANSITION / 4), 1.0)
            # 取消缓动函数 eased_progress = ease_out_cubic(progress)
            eased_progress = progress
            # 加速消失 把255变100
            self.old_img.opacity = int(100 * (1 - eased_progress))
            if progress >= 1.0:
                clock.unschedule(self.fade_out_old)
                # 只在这里停止动画，不设置 self.old_img = None

    def show_next_manual(self):
        if self.transitioning:
            clock.unschedule(self.slide_left)
            clock.unschedule(self.fade_out_old)
            self.transitioning = False
            if self.old_img:
                self.old_img = None

        self.manual_mode = True
        next_index = (self.current_index + 1) % len(self.images)
        path = self.images[next_index]
        self.current_index = next_index
        
        # 删除旧的当前精灵
        self.current = self._safe_delete_sprite(self.current, "当前精灵")
        
        self.current = self.draw_sigle_pic(path)

    def show_prev_manual(self):
        if self.transitioning:
            clock.unschedule(self.slide_left)
            clock.unschedule(self.fade_out_old)
            self.transitioning = False
            if self.old_img:
                self.old_img = None

        self.manual_mode = True
        prev_index = (self.current_index - 1) % len(self.images)
        path = self.images[prev_index]
        self.current_index = prev_index
        
        # 删除旧的当前精灵
        self.current = self._safe_delete_sprite(self.current, "当前精灵")
        
        self.current = self.draw_sigle_pic(path)

    def exit_thumbnail_mode(self):
        self.thumbnail_mode = False
        self.manual_mode = False
        self.current_index = self.thumbnail_page
        if self.current_index >= len(self.images):
            self.current_index = 0
        path = self.images[self.current_index]
        
        # 只有在需要时才删除当前精灵并重新加载
        if self.current and hasattr(self.current, 'delete'):
            try:
                self.current.delete()
            except Exception as e:
                print(f"删除当前 sprite 出错: {e}")
        self.current = self.draw_sigle_pic(path)
        self._cleanup_thumbnails()

    def _cleanup_thumbnails(self):
        """清理缩略图资源"""
        # 使用 image_processor 中的清理函数
        cleanup_func = cleanup_thumbnails()
        cleanup_func()