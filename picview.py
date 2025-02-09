import pyglet
import os
import random
from glob import glob
from pyglet import clock
from pyglet.window import key, mouse
import time
from collections import OrderedDict

# 配置区
FOLDER = "./img"
DURATION = 5
TRANSITION = 1
MAX_IMAGES = 20  # 最大缓存图片数量

# 缓动函数库
def ease_out_quad(t):
    return t * (2 - t)

def ease_out_cubic(t):
    return 1 - (1 - t)**3

window = pyglet.window.Window(width=800, height=600, resizable=True)

images = [f for f in glob(os.path.join(FOLDER, '**/*.*'), recursive=True)
          if f.lower().endswith(('.png', '.jpg', '.jpeg', '.webp'))]
# random.shuffle(images)

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
        self.history = []        # 存储历史图片路径，用于切换上一张

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

    def load_next(self):
        if not images:
            return
        # 获取下一张图片路径，并进行循环
        path = images.pop(0)
        images.append(path)
        self.next_img = self.get_sprite_from_path(path)
        self.history.append(path)

    def scale_to_fit(self, sprite, max_width, max_height):
        scale = min(max_width / sprite.width, max_height / sprite.height)
        sprite.update(scale=scale)

    def center_sprite(self, sprite, max_width, max_height):
        sprite.x = (max_width - sprite.width) // 2
        sprite.y = (max_height - sprite.height) // 2

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
                # 不调用 delete()，直接丢弃引用即可
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
        self.load_next()
        # 直接放弃当前 sprite，不调用 delete()
        self.current = self.next_img
        self.next_img = None

    def show_prev_manual(self):
        # 如果没有前一张，则不操作
        if len(self.history) < 2:
            return

        # 停止任何动画
        if self.transitioning:
            clock.unschedule(self.slide_left)
            clock.unschedule(self.fade_out_old)
            self.transitioning = False
            self.old_img = None

        self.manual_mode = True
        # 弹出当前图片的路径
        self.history.pop()
        prev_path = self.history[-1]
        sprite = self.get_sprite_from_path(prev_path)
        self.current = sprite

slides = SlideShow()
slides.load_next()
# 初次加载时直接显示第一张图片
slides.current = slides.next_img
slides.next_img = None

@window.event
def on_draw():
    window.clear()
    if slides.transitioning:
        if slides.old_img:
            slides.old_img.draw()
        slides.next_img.draw()
    else:
        if slides.current:
            slides.current.draw()

@window.event
def on_key_press(symbol, modifiers):
    if symbol == key.SPACE:
        # 恢复自动播放模式，从当前图片开始
        slides.manual_mode = False
    elif symbol == key.RIGHT:
        slides.show_next_manual()
    elif symbol == key.LEFT:
        slides.show_prev_manual()

def update(dt):
    # 仅当不处于手动模式时，自动切换
    if not slides.manual_mode:
        slides.load_next()
        slides.transition(dt)

# 对自动播放进行定时调度
pyglet.clock.schedule_interval(update, DURATION)
pyglet.app.run()
