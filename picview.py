import pyglet
import os
import random
from glob import glob
from pyglet import clock
from pyglet.window import key, mouse
import time
from collections import OrderedDict
import math

# 配置区
FOLDER = "./img"
DURATION = 5
TRANSITION = 1
MAX_IMAGES = 20  # 最大缓存图片数量
PROGRESS_BAR_HEIGHT = 10  # 新增进度条高度配置

# 缓动函数库
def ease_out_quad(t):
    return t * (2 - t)

def ease_out_cubic(t):
    return 1 - (1 - t)**3

window = pyglet.window.Window(width=900, height=600, resizable=True, style="None")

images = [f for f in glob(os.path.join(FOLDER, '**/*.*'), recursive=True)
          if f.lower().endswith(('.png', '.jpg', '.jpeg', '.webp'))]
random.shuffle(images)  # 初始随机排序

# 缓存 Image 对象而非 Sprite，减少长期引用
image_cache = OrderedDict()

class SlideShow:
    def __init__(self):
        self.batch = pyglet.graphics.Batch()
        self.current = None      # 当前显示的 Sprite
        self.next_img = None     # 下一张 Sprite（预加载）
        self.transitioning = False
        self.old_img = None      # 过渡中的旧 Sprite
        self.animation_start_time = 0
        self.manual_mode = False # 手动模式标识，True 时停止自动播放
        self.current_index = 0   # 当前图片索引
        # 新增缩略图模式相关属性
        self.thumbnail_mode = False
        self.thumbnail_page = 0  # 当前缩略图页码
        # 新增进度条相关属性
        self.progress_bg_color = (11, 11, 11, 255)    # #333
        self.progress_fg_color = (102, 102, 102, 255) # #666
        

    def get_sprite_from_path(self, path):
        if path not in image_cache:
            img = pyglet.image.load(path)
            image_cache[path] = img
            # 加载新图片后清理超出缓存数量的图片
            while len(image_cache) > MAX_IMAGES:
                oldest_path, oldest_img = image_cache.popitem(last=False)
                try:
                    oldest_texture = oldest_img.get_texture()
                    oldest_texture.delete()
                except Exception as e:
                    print(f"清理缓存时出错: {e}")
        else:
            print(f"Using cached: {path}")
            image_cache.move_to_end(path)
            # 即使使用缓存，也检查是否需要清理
            while len(image_cache) > MAX_IMAGES:
                oldest_path, oldest_img = image_cache.popitem(last=False)
                try:
                    oldest_texture = oldest_img.get_texture()
                    oldest_texture.delete()
                except Exception as e:
                    print(f"清理缓存时出错: {e}")
        sprite = pyglet.sprite.Sprite(image_cache[path], batch=self.batch)
        self.scale_to_fit(sprite, window.width, window.height)
        self.center_sprite(sprite, window.width, window.height)
        return sprite

    def get_thumbnail_sprite(self, path):
        # 与 get_sprite_from_path 类似，但不加入 batch，并调整为缩略图尺寸
        if path not in image_cache:
            img = pyglet.image.load(path)
            image_cache[path] = img
            while len(image_cache) > MAX_IMAGES:
                oldest_path, oldest_img = image_cache.popitem(last=False)
                try:
                    oldest_texture = oldest_img.get_texture()
                    oldest_texture.delete()
                except Exception as e:
                    print(f"清理缓存时出错: {e}")
        else:
            image_cache.move_to_end(path)
        sprite = pyglet.sprite.Sprite(image_cache[path])
        return sprite

    def draw_thumbnails(self):
        # 每页显示10张缩略图，采用 5 列 2 行的布局
        total = len(images)
        start_index = self.thumbnail_page
        end_index = min(start_index + 10, total)
        padding = 10
        columns = 5
        rows = 2

        # 为每个单元格（cell）计算固定宽度和高度
        cell_width = (window.width - (columns + 1) * padding) / columns
        cell_height = (window.height - (rows + 1) * padding) / rows

        for idx in range(start_index, end_index):
            path = images[idx]
            sprite = self.get_thumbnail_sprite(path)
            # 计算缩放因子，使图片能适应单元格（保持长宽比）
            scale_w = cell_width / sprite.image.width
            scale_h = cell_height / sprite.image.height
            scale_factor = min(scale_w, scale_h)
            sprite.update(scale=scale_factor)
            # 确认缩放后图片的尺寸
            thumb_w, thumb_h = sprite.width, sprite.height

            # 根据在当前页的位置计算行列索引
            pos_in_page = idx - start_index
            col = pos_in_page % columns
            row = pos_in_page // columns

            # 计算每个单元格的左下角坐标
            cell_x = padding + col * (cell_width + padding)
            cell_y = window.height - padding - (row + 1) * cell_height - row * padding

            # 居中显示图片
            sprite.x = cell_x + (cell_width - thumb_w) / 2
            sprite.y = cell_y + (cell_height - thumb_h) / 2
            sprite.draw()

    def scale_to_fit(self, sprite, max_width, max_height):
        scale = min(max_width / sprite.width, max_height / sprite.height)
        sprite.update(scale=scale)

    def center_sprite(self, sprite, max_width, max_height):
        sprite.x = (max_width - sprite.width) // 2
        sprite.y = (max_height - sprite.height) // 2

    def load_next(self):
        if not images:
            return
        # 计算下一张索引
        next_index = (self.current_index + 1) % len(images)
        path = images[next_index]
        self.next_img = self.get_sprite_from_path(path)
        self.current_index = next_index

    def transition(self, dt):
        # 如果处于手动模式或正处于过渡中，则跳过自动过渡
        if self.manual_mode or self.transitioning or not self.next_img:
            return

        self.transitioning = True
        self.animation_start_time = time.time()

        # 记录旧 Sprite 并启动动画
        if self.current:
            self.old_img = self.current
            self.old_img.opacity = 255

        # 随机选择动画效果，目前仅实现 slide_left
        effect = random.choice(['slide_left'])
        if effect == 'slide_left':
            self.next_img.x = window.width  # 初始位置在右侧
            clock.schedule_interval(self.slide_left, 1/60)
            clock.schedule_interval(self.fade_out_old, 1/60)

    def slide_left(self, dt):
        elapsed = time.time() - self.animation_start_time
        progress = min(elapsed / TRANSITION, 1.0)
        eased_progress = ease_out_cubic(progress)

        # 计算新位置
        target_x = (window.width - self.next_img.width) // 2
        self.next_img.x = window.width - (window.width - target_x) * eased_progress

        if progress >= 1.0:
            # 动画结束，清理资源
            clock.unschedule(self.slide_left)
            self.current = self.next_img
            self.next_img = None
            self.transitioning = False
            if self.old_img:
                self.old_img = None

    def fade_out_old(self, dt):
        if self.old_img:
            elapsed = time.time() - self.animation_start_time
            progress = min(elapsed / TRANSITION, 1.0)
            eased_progress = ease_out_quad(progress)
            self.old_img.opacity = int(255 * (1 - eased_progress))

            if progress >= 1.0:
                clock.unschedule(self.fade_out_old)

    def show_next_manual(self):
        # 如果处于过渡中，停止动画
        if self.transitioning:
            clock.unschedule(self.slide_left)
            clock.unschedule(self.fade_out_old)
            self.transitioning = False
            self.old_img = None

        self.manual_mode = True
        # 直接加载下一张
        next_index = (self.current_index + 1) % len(images)
        path = images[next_index]
        self.current_index = next_index
        self.current = self.get_sprite_from_path(path)

    def show_prev_manual(self):
        # 计算上一张索引
        prev_index = (self.current_index - 1) % len(images)
        
        # 停止任何动画
        if self.transitioning:
            clock.unschedule(self.slide_left)
            clock.unschedule(self.fade_out_old)
            self.transitioning = False
            self.old_img = None

        self.manual_mode = True
        # 加载上一张
        path = images[prev_index]
        self.current_index = prev_index
        self.current = self.get_sprite_from_path(path)

    def exit_thumbnail_mode(self):
        """
        退出缩略图模式时，更新当前索引为当前页第一张
        """
        self.thumbnail_mode = False
        self.manual_mode = False
        self.current_index = self.thumbnail_page
        if self.current_index >= len(images):
            self.current_index = 0
        # 加载当前索引的图片
        path = images[self.current_index]
        self.current = self.get_sprite_from_path(path)

slides = SlideShow()
# 初次加载当前图片
if images:
    slides.current = slides.get_sprite_from_path(images[0])


@window.event
def on_draw():
    window.clear()
    if slides.thumbnail_mode:
        slides.draw_thumbnails()
    elif slides.transitioning:
        if slides.old_img:
            slides.old_img.draw()
        slides.next_img.draw()
    else:
        if slides.current:
            slides.current.draw()
    
    # 新增进度条绘制逻辑
    if not slides.manual_mode and not slides.thumbnail_mode and images:
        # 计算进度条参数
        total = len(images)
        progress = (slides.current_index + 1) / total  # +1 因为索引从0开始
        bar_width = window.width * progress

        # 绘制背景条
        bg = pyglet.shapes.Rectangle(0, 0, window.width, PROGRESS_BAR_HEIGHT,
                                     color=slides.progress_bg_color[:3])
        bg.opacity = slides.progress_bg_color[3]
        bg.draw()
        # 绘制前景条
        fg = pyglet.shapes.Rectangle(0, 0, bar_width, PROGRESS_BAR_HEIGHT,
                                     color=slides.progress_fg_color[:3])
        fg.opacity = slides.progress_fg_color[3]
        fg.draw()

@window.event
def on_resize(width, height):
    # 新增窗口大小变化时重新定位精灵
    if slides.current:
        slides.scale_to_fit(slides.current, width, height)
        slides.center_sprite(slides.current, width, height)
    if slides.next_img:
        slides.scale_to_fit(slides.next_img, width, height)
        slides.center_sprite(slides.next_img, width, height)


@window.event
def on_key_press(symbol, modifiers):
    # 回车键切换缩略图模式
    if symbol in (key.ENTER, key.RETURN):
        if slides.thumbnail_mode:
            slides.exit_thumbnail_mode()
            return
        else:
            slides.thumbnail_mode = True
            slides.thumbnail_page = slides.current_index  # 当前图片作为缩略图列表的第一张
            slides.manual_mode = True  # 停止自动播放
            return

    # 在缩略图模式下使用上、下键翻页，每次移动10张
    if slides.thumbnail_mode:
        if symbol == key.UP:
            if slides.thumbnail_page - 10 >= 0:
                slides.thumbnail_page -= 10
            return
        elif symbol == key.DOWN:
            if slides.thumbnail_page + 10 < len(images):
                slides.thumbnail_page += 10
            return

    # 普通播放模式下的按键响应
    if symbol == key.SPACE:
        # 恢复自动播放模式，从当前图片开始
        slides.manual_mode = False
    elif symbol == key.RIGHT:
        slides.show_next_manual()
    elif symbol == key.LEFT:
        slides.show_prev_manual()

def update(dt):
    # 仅当不处于手动模式且不在缩略图模式下时自动切换
    if not slides.manual_mode and not slides.thumbnail_mode:
        slides.load_next()
        slides.transition(dt)

# 对自动播放进行定时调度
pyglet.clock.schedule_interval(update, DURATION)
pyglet.app.run()
