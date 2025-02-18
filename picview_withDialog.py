import pyglet
import os
import random
from glob import glob
from pyglet import clock
from pyglet.window import key, mouse
import time
from collections import OrderedDict
import math
import AppKit

def choose_folder():
    panel = AppKit.NSOpenPanel.openPanel()
    panel.setCanChooseFiles_(False)
    panel.setCanChooseDirectories_(True)
    panel.setAllowsMultipleSelection_(False)
    panel.setMessage_("请选择图片目录")
    if panel.runModal():
        # 选择完成后隐藏窗口
        panel.orderOut_(None)
        selected_path = panel.URLs()[0].path()
    else:
        selected_path = "./img"
    # 通过删除引用，让垃圾回收器在合适的时机回收该对象
    panel = None
    return selected_path

FOLDER = choose_folder()

# 配置区
DURATION = 5
TRANSITION = 1
MAX_IMAGES = 10  # 最大缓存图片数量
PROGRESS_BAR_HEIGHT = 5

def ease_out_quad(t):
    return t * (2 - t)

def ease_out_cubic(t):
    return 1 - (1 - t)**3

window = pyglet.window.Window(width=900, height=600, resizable=True, style="None", vsync=True )

images = [f for f in glob(os.path.join(FOLDER, '**/*.*'), recursive=True)
          if f.lower().endswith(('.png', '.jpg', '.jpeg', '.webp'))]
random.shuffle(images)

# 缓存 Image 对象而非 Sprite
image_cache = OrderedDict()

class SlideShow:
    def __init__(self):
        self.batch = pyglet.graphics.Batch()
        self.current = None      # 当前显示的 Sprite
        self.next_img = None     # 下一张 Sprite（预加载）
        self.transitioning = False
        self.old_img = None      # 过渡中的旧 Sprite
        self.animation_start_time = 0
        self.manual_mode = False
        self.current_index = 0
        self.thumbnail_mode = False
        self.thumbnail_page = 0  # 当前缩略图页码（images 中的索引）
        self.thumbnail_cache = {}  # 预生成的缩略图页面缓存
        self.progress_bg_color = (11, 11, 11, 255)    # #333
        self.progress_fg_color = (102, 102, 102, 255)   # #666
        self.progress_bg = pyglet.shapes.Rectangle(0, 0, 0, 0, color=(0,0,0))
        self.progress_fg = pyglet.shapes.Rectangle(0, 0, 0, 0, color=(0,0,0))
        self.progress_bg.visible = False
        self.progress_fg.visible = False
        self.preload_thumbnail_pages()

    def preload_thumbnail_pages(self):
        num_pages_to_preload = int(MAX_IMAGES/10)
        print(f"缓存页数：{num_pages_to_preload}")
        try:
	        for i in range(num_pages_to_preload):
	            start_index = i * 10
	            if start_index < len(images):
	                self.thumbnail_cache[start_index] = self.generate_thumbnail_page(start_index)
        except Exception as e:
            print(f"创建缩略图缓存出错 {e}")

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

    def get_sprite_from_path(self, path, add_to_batch=True):
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
            while len(image_cache) > MAX_IMAGES:
                oldest_path, oldest_img = image_cache.popitem(last=False)
                try:
                    oldest_texture = oldest_img.get_texture()
                    oldest_texture.delete()
                except Exception as e:
                    print(f"清理缓存时出错: {e}")
        if add_to_batch:
            sprite = pyglet.sprite.Sprite(image_cache[path], batch=self.batch)
        else:
            sprite = pyglet.sprite.Sprite(image_cache[path])
        self.scale_to_fit(sprite, window.width, window.height)
        self.center_sprite(sprite, window.width, window.height)
        window.set_caption(os.path.basename(path))
        return sprite

    def get_thumbnail_sprite(self, path):
        return self.get_sprite_from_path(path, add_to_batch=False)

    def generate_thumbnail_page(self, start_index):
        sprites = []
        total = len(images)
        end_index = min(start_index + 10, total)
        padding = 10
        columns = 5
        rows = 2
        cell_width = (window.width - (columns + 1) * padding) / columns
        cell_height = (window.height - (rows + 1) * padding) / rows

        for idx in range(start_index, end_index):
            path = images[idx]
            sprite = self.get_thumbnail_sprite(path)
            scale_w = cell_width / sprite.image.width
            scale_h = cell_height / sprite.image.height
            scale_factor = min(scale_w, scale_h)
            sprite.update(scale=scale_factor)
            thumb_w, thumb_h = sprite.width, sprite.height
            pos_in_page = idx - start_index
            col = pos_in_page % columns
            row = pos_in_page // columns
            cell_x = padding + col * (cell_width + padding)
            cell_y = window.height - padding - (row + 1) * cell_height - row * padding
            sprite.x = cell_x + (cell_width - thumb_w) / 2
            sprite.y = cell_y + (cell_height - thumb_h) / 2
            sprites.append(sprite)
        return sprites

    def draw_thumbnails(self):
        if self.thumbnail_page not in self.thumbnail_cache:
            self.thumbnail_cache[self.thumbnail_page] = self.generate_thumbnail_page(self.thumbnail_page)
        for sprite in self.thumbnail_cache[self.thumbnail_page]:
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
        # 获取下一个 sprite，但不改变当前 batch 里的 sprite
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
        effect = random.choice(['slide_left'])
        if effect == 'slide_left':
            self.next_img.x = window.width
            clock.schedule_interval(self.slide_left, 1/60)
            clock.schedule_interval(self.fade_out_old, 1/60)

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
            # 删除过渡期间的旧 sprite
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
        # 清理缩略图缓存时删除所有缩略图 sprite
        for page in self.thumbnail_cache.values():
            for sprite in page:
                try:
                    sprite.delete()
                except Exception as e:
                    print(f"删除缩略图 sprite 出错: {e}")
        self.thumbnail_cache.clear()

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
        # 窗口尺寸变化时重建缩略图缓存
        for page in slides.thumbnail_cache.values():
            for sprite in page:
                try:
                    sprite.delete()
                except Exception as e:
                    print(f"删除缩略图 sprite 出错: {e}")
        slides.thumbnail_cache.clear()

@window.event
def on_key_press(symbol, modifiers):
    if symbol in (key.ENTER, key.RETURN):
        if slides.thumbnail_mode:
            slides.exit_thumbnail_mode()
            return
        else:
            slides.thumbnail_mode = True
            slides.thumbnail_page = slides.current_index
            slides.manual_mode = True
            # for page in slides.thumbnail_cache.values():
            #     for sprite in page:
            #         try:
            #             sprite.delete()
            #         except Exception as e:
            #             print(f"删除缩略图 sprite 出错: {e}")
            # slides.thumbnail_cache.clear()
            return
    if slides.thumbnail_mode:
        if symbol == key.UP:
            if slides.thumbnail_page - 10 >= 0:
                slides.thumbnail_page -= 10
                for page in slides.thumbnail_cache.values():
                    for sprite in page:
                        try:
                            sprite.delete()
                        except Exception as e:
                            print(f"删除缩略图 sprite 出错: {e}")
                slides.thumbnail_cache.clear()
            return
        elif symbol == key.DOWN:
            if slides.thumbnail_page + 10 < len(images):
                slides.thumbnail_page += 10
                for page in slides.thumbnail_cache.values():
                    for sprite in page:
                        try:
                            sprite.delete()
                        except Exception as e:
                            print(f"删除缩略图 sprite 出错: {e}")
                slides.thumbnail_cache.clear()
            return
    else:
        if symbol == key.SPACE:
            slides.manual_mode = False
        elif symbol == key.RIGHT:
            slides.show_next_manual()
        elif symbol == key.LEFT:
            slides.show_prev_manual()

def update(dt):
    if not slides.manual_mode and not slides.thumbnail_mode:
        slides.load_next()
        slides.transition(dt)
        window.invalid = True

pyglet.clock.schedule_interval(update, DURATION)
pyglet.app.run()
