import pyglet
import os
import random
from glob import glob
from pyglet import clock
from pyglet.window import key, mouse
import time
from collections import OrderedDict
import math
import subprocess # 用于执行 AppleScript 脚本打开文件选择对话框，代替pyobjc
from concurrent.futures import ThreadPoolExecutor
import threading
from PIL import Image

import psutil
process = psutil.Process()

def print_memory():
    mem = process.memory_info().rss // 1024
    textures = 0
    valid_images = 0
    
    for img in image_cache.values():
        try:
            # 安全获取纹理对象
            texture = img.get_texture()
            if texture:
                textures += 1
            valid_images += 1
        except AttributeError:
            # 处理没有get_texture方法的对象
            pass
        except Exception as e:
            print(f"纹理检测错误: {e}")
    
    print(f"内存使用: {mem} KB | 有效缓存: {valid_images}/{len(image_cache)} | 活跃纹理: {textures}")

pyglet.clock.schedule_interval(lambda dt: print_memory(), 5)


def choose_folder():
    # AppleScript 脚本（直接返回 POSIX 路径）
    script = '''
    tell application "System Events"
        activate
        set selectedFolder to POSIX path of (choose folder with prompt "请选择图片目录")
        return selectedFolder
    end tell
    '''
    
    try:
        # 执行脚本并捕获输出
        result = subprocess.check_output(['osascript', '-e', script], 
                                        stderr=subprocess.STDOUT,
                                        universal_newlines=True)
        # 清理路径（去除换行符和空格）
        return result.strip()
    except subprocess.CalledProcessError as e:
        # 用户取消选择或脚本错误时返回默认路径
        print(f"文件夹选择取消或出错: {e.output}")
        return "./img"

FOLDER = choose_folder()

# 配置区
DURATION = 5
TRANSITION = 1
MAX_IMAGES = 2
PROGRESS_BAR_HEIGHT = 5
THREAD_POOL_SIZE = 4
THUMBNAIL_SIZE = (500, 500)

def ease_out_quad(t):
    return t * (2 - t)

def ease_out_cubic(t):
    return 1 - (1 - t)**3

config = pyglet.gl.Config(double_buffer=True)
window = pyglet.window.Window(config=config, width=900, height=600, resizable=True, style="None", vsync=True)

images = [f for f in glob(os.path.join(FOLDER, '**/*.*'), recursive=True)
          if f.lower().endswith(('.png', '.jpg', '.jpeg', '.webp'))]
random.shuffle(images)

image_cache = OrderedDict()

class SlideShow:
    def __init__(self):
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
        self.thumbnail_cache = {}
        self.progress_bg_color = (11, 11, 11, 255)
        self.progress_fg_color = (102, 102, 102, 255)
        self.progress_bg = pyglet.shapes.Rectangle(0, 0, 0, 0, color=(0,0,0))
        self.progress_fg = pyglet.shapes.Rectangle(0, 0, 0, 0, color=(0,0,0))
        self.progress_bg.visible = False
        self.progress_fg.visible = False
        
        # 多线程相关初始化
        self.executor = ThreadPoolExecutor(max_workers=THREAD_POOL_SIZE)
        self.lock = threading.Lock()
        self.pending_tasks = []
        self.thumbnail_data_cache = {}

    def update_progress(self, progress):
        if self.manual_mode or self.thumbnail_mode or not images:
            self.progress_bg.visible = False
            self.progress_fg.visible = False
            return

        total_width = window.width
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

    def clean_cache(self):
        while len(image_cache) > MAX_IMAGES:
            oldest_path, oldest_img = image_cache.popitem(last=False)
            try:
                # 安全释放纹理资源
                if hasattr(oldest_img, 'get_texture'):
                    texture = oldest_img.get_texture()
                    if texture:
                        texture.delete()
                # 解除所有引用
                del oldest_img
                print(f"清理缓存完成")
            except Exception as e:
                print(f"清理缓存时出错: {e}")

    def get_sprite_from_path(self, path, add_to_batch=True):
        if path not in image_cache:
            try:
                # 确保加载的是Texture
                img = pyglet.image.load(path)
                if not isinstance(img, pyglet.image.Texture):
                    img = img.get_texture()
                image_cache[path] = img
            except Exception as e:
                print(f"加载图片失败: {path} - {e}")
                return None
        else:
            image_cache.move_to_end(path)
        
        self.clean_cache()
        
        try:
            sprite = pyglet.sprite.Sprite(image_cache[path], batch=self.batch if add_to_batch else None)
            self.scale_to_fit(sprite, window.width, window.height)
            self.center_sprite(sprite, window.width, window.height)
            window.set_caption(os.path.basename(path))
            return sprite
        except Exception as e:
            print(f"创建精灵失败: {e}")
            return None

    def generate_thumbnail_data(self, path):
        """ 在后台线程中生成缩略图数据 """
        try:
            with Image.open(path) as img:
                img.thumbnail(THUMBNAIL_SIZE)
                # 垂直翻转图像适配pyglet坐标系
                img = img.transpose(Image.FLIP_TOP_BOTTOM)
                return path, img.convert("RGBA").tobytes(), img.size
        except Exception as e:
            print(f"生成缩略图失败: {e}")
            return None

    def create_sprite_from_data(self, data):
        """ 在主线程创建精灵 """
        try:
            if not pyglet.gl.current_context:
                print("无OpenGL上下文，跳过创建精灵")
                return None
            path, image_data, size = data
            image = pyglet.image.ImageData(size[0], size[1], 'RGBA', image_data)
            sprite = pyglet.sprite.Sprite(image)
            sprite.path = path  # 保存路径用于点击检测
            return sprite
        except Exception as e:
            print(f"创建精灵失败: {e}")
            return None

    def generate_thumbnail_page(self, start_index):
        """ 生成缩略图页面（多线程版） """
        total = len(images)
        end_index = min(start_index + 10, total)
        page_key = (start_index, window.width, window.height)
        
        if page_key in self.thumbnail_cache:
            return self.thumbnail_cache[page_key]

        # 创建有效的透明占位符
        placeholder_img = pyglet.image.ImageData(1, 1, 'RGBA', b'\x00\x00\x00\x00')
        sprites = []
        for idx in range(start_index, end_index):
            path = images[idx]
            if path in self.thumbnail_data_cache:
                data = self.thumbnail_data_cache[path]
                sprites.append(self.create_sprite_from_data(data))
            else:
                future = self.executor.submit(self.generate_thumbnail_data, path)
                future.add_done_callback(lambda f, idx=idx: self._thumbnail_ready(f, start_index, idx))
                self.pending_tasks.append(future)
                # 创建临时占位精灵
                placeholder = pyglet.sprite.Sprite(placeholder_img)
                placeholder.width = THUMBNAIL_SIZE[0]
                placeholder.height = THUMBNAIL_SIZE[1]
                sprites.append(placeholder)

        self.thumbnail_cache[page_key] = sprites
        return self.thumbnail_cache[page_key]

    def _thumbnail_ready(self, future, page_start, idx_in_page):
        """ 缩略图生成完成回调 """
        try:
            result = future.result()

            path, image_data, size = result
            def update_thumbnail(dt):

                with self.lock:
                    self.thumbnail_data_cache[path] = result
                    
                    page_key = (page_start, window.width, window.height)
                    if page_key in self.thumbnail_cache:
                        sprite = self.create_sprite_from_data(result)
                        self._position_thumbnail(sprite, page_start, idx_in_page)
                        # 安全替换缩略图缓存
                        self.thumbnail_cache[page_key][idx_in_page - page_start] = sprite
            pyglet.clock.schedule_once(update_thumbnail, 0)
        except Exception as e:
            print(f"处理缩略图回调时出错: {e}")

    def _position_thumbnail(self, sprite, start_index, idx):
        """ 定位缩略图位置 """
        # 在计算缩放前添加安全检查
        if sprite.width == 0 or sprite.height == 0:
            return
        padding = 10
        columns = 5
        rows = 2
        cell_width = (window.width - (columns + 1) * padding) / columns
        cell_height = (window.height - (rows + 1) * padding) / rows

        pos_in_page = idx - start_index
        col = pos_in_page % columns
        row = pos_in_page // columns
        cell_x = padding + col * (cell_width + padding)
        cell_y = window.height - padding - (row + 1) * cell_height - row * padding

        scale_w = cell_width / sprite.width
        scale_h = cell_height / sprite.height
        scale_factor = min(scale_w, scale_h)
        sprite.update(scale=scale_factor)
        sprite.x = cell_x + (cell_width - sprite.width) / 2
        sprite.y = cell_y + (cell_height - sprite.height) / 2

    def draw_thumbnails(self):
        page_key = (self.thumbnail_page, window.width, window.height)
        sprites = self.generate_thumbnail_page(self.thumbnail_page)
        for sprite in sprites:
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
        next_index = (self.current_index + 1) % len(images)
        path = images[next_index]
        self.next_img = self.get_sprite_from_path(path)
        self.current_index = next_index

    def transition(self, dt):
        if self.manual_mode or self.transitioning or not self.next_img:
            return
        self.transitioning = True
        self.animation_start_time = time.time()
        if self.current:
            self.old_img = self.current
            self.old_img.opacity = 255
        self.next_img.x = window.width
        clock.schedule_interval(self.slide_left, 1/59)
        clock.schedule_interval(self.fade_out_old, 1/59)

    def slide_left(self, dt):
        elapsed = time.time() - self.animation_start_time
        progress = min(elapsed / TRANSITION, 1.0)
        eased_progress = ease_out_cubic(progress)
        target_x = (window.width - self.next_img.width) // 2
        self.next_img.x = window.width - (window.width - target_x) * eased_progress
        if progress >= 1.0:
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
        if self.transitioning:
            clock.unschedule(self.slide_left)
            clock.unschedule(self.fade_out_old)
            self.transitioning = False
            if self.old_img:
                self.old_img = None

        self.manual_mode = True
        next_index = (self.current_index + 1) % len(images)
        path = images[next_index]
        self.current_index = next_index
        self.current = self.get_sprite_from_path(path)

    def show_prev_manual(self):
        if self.transitioning:
            clock.unschedule(self.slide_left)
            clock.unschedule(self.fade_out_old)
            self.transitioning = False
            if self.old_img:
                self.old_img = None

        self.manual_mode = True
        prev_index = (self.current_index - 1) % len(images)
        path = images[prev_index]
        self.current_index = prev_index
        self.current = self.get_sprite_from_path(path)

    def exit_thumbnail_mode(self):
        self.thumbnail_mode = False
        self.manual_mode = False
        self.current_index = self.thumbnail_page
        if self.current_index >= len(images):
            self.current_index = 0
        path = images[self.current_index]
        if self.current:
            try:
                self.current.delete()
            except Exception as e:
                print(f"删除当前 sprite 出错: {e}")
        self.current = self.get_sprite_from_path(path)
        self._cleanup_thumbnails()

    def _cleanup_thumbnails(self):
        def do_cleanup(dt):
            # 终止进行中的任务
            for task in self.pending_tasks:
                if not task.done():
                    task.cancel()
            self.pending_tasks.clear()

            # 清空数据缓存
            self.thumbnail_data_cache.clear()

            # 释放所有缩略图精灵
            deleted_count = 0
            for page in self.thumbnail_cache.values():
                for sprite in page:
                    try:
                        if sprite is None:  # 跳过空精灵
                            continue
                        
                        # 安全释放纹理资源
                        if hasattr(sprite, 'image') and sprite.image is not None:
                            # 检查是否存在get_texture方法
                            if hasattr(sprite.image, 'get_texture'):
                                texture = sprite.image.get_texture()
                                if texture:
                                    texture.delete()
                                    print(f"删除缩略图 texture ")
                            # 解除图像引用
                            sprite.image = None
                        
                        # 删除精灵本身
                        if hasattr(sprite, 'delete'):
                            sprite.delete()
                            deleted_count += 1
                            print(f"删除缩略图 sprite : {deleted_count}")
                    except AttributeError as e:
                        if "'NoneType'" in str(e):  # 忽略None相关错误
                            pass
                    except Exception as e:
                        print(f"安全清理失败: {str(e)[:50]}...")  # 截短错误信息

            # 清空缓存
            self.thumbnail_cache.clear()
            # 强制垃圾回收（可选）
            import gc
            gc.collect()
        
        pyglet.clock.schedule_once(do_cleanup, 0)

slides = SlideShow()
if images:
    slides.current = slides.get_sprite_from_path(images[0])
    window.set_caption(os.path.basename(images[0]))

@window.event
def on_draw():
    window.clear()
    if slides.thumbnail_mode:
        slides.draw_thumbnails()
    elif slides.transitioning:
        if slides.old_img:
            slides.old_img.draw()
        if slides.next_img:
            slides.next_img.draw()
    else:
        if slides.current:
            slides.current.draw()
    if not slides.manual_mode and not slides.thumbnail_mode and images:
        progress = (slides.current_index + 1) / len(images)
        slides.update_progress(progress)
        slides.progress_bg.draw()
        slides.progress_fg.draw()

@window.event
def on_resize(width, height):
    if slides.current:
        slides.scale_to_fit(slides.current, width, height)
        slides.center_sprite(slides.current, width, height)
    if slides.next_img:
        slides.scale_to_fit(slides.next_img, width, height)
        slides.center_sprite(slides.next_img, width, height)
    if slides.thumbnail_mode:
        slides._cleanup_thumbnails()

@window.event
def on_key_press(symbol, modifiers):
    if symbol in (key.ENTER, key.RETURN):
        if slides.thumbnail_mode:
            slides.exit_thumbnail_mode()
        else:
            slides.thumbnail_mode = True
            slides.thumbnail_page = slides.current_index
            slides.manual_mode = True
        return
    if slides.thumbnail_mode:
        if symbol == key.UP:
            if slides.thumbnail_page - 10 >= 0:
                slides.thumbnail_page -= 10
                slides._cleanup_thumbnails()
        elif symbol == key.DOWN:
            if slides.thumbnail_page + 10 < len(images):
                slides.thumbnail_page += 10
                slides._cleanup_thumbnails()
    else:
        if symbol == key.SPACE:
            slides.manual_mode = False
        elif symbol == key.RIGHT:
            if slides.current_index < len(images) - 1:
                slides.show_next_manual()
        elif symbol == key.LEFT:
            if slides.current_index > 0:
                slides.show_prev_manual()
@window.event
def on_close():
    # 释放主图片缓存
    for img in image_cache.values():
        try:
            img.get_texture().delete()
        except: pass
    image_cache.clear()
    
    # 释放幻灯片资源
    if slides.current:
        slides.current.image.get_texture().delete()
    if slides.next_img:
        slides.next_img.image.get_texture().delete()
    
    slides._cleanup_thumbnails()
    slides.executor.shutdown(wait=False)
    window.close()
    pyglet.app.exit()

def update(dt):
    if not slides.manual_mode and not slides.thumbnail_mode:
        slides.load_next()
        slides.transition(dt)
        window.invalid = True

pyglet.clock.schedule_interval(update, DURATION)
pyglet.app.run()
