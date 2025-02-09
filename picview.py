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
MAX_IMAGES = 3  # 最大缓存图片数量

# 缓动函数库
def ease_out_quad(t):
    return t * (2 - t)

def ease_out_cubic(t):
    return 1 - (1 - t)**3

window = pyglet.window.Window(width=800, height=600, resizable=True)

images = [f for f in glob(os.path.join(FOLDER, '**/*.*'), recursive=True)
          if f.lower().endswith(('.png', '.jpg', '.jpeg', '.webp'))]
random.shuffle(images)

# 缓存Image对象而非Sprite，减少长期引用
image_cache = OrderedDict()

class SlideShow:
    def __init__(self):
        self.batch = pyglet.graphics.Batch()
        self.current = None      # 当前显示的Sprite
        self.next_img = None     # 下一张Sprite（预加载）
        self.transitioning = False
        self.old_img = None      # 过渡中的旧Sprite
        self.animation_start_time = 0

    def load_next(self):
        if not images:
            return
        
        # 获取下一张图片路径
        path = images.pop(0)
        images.append(path)
        
        # 缓存管理
        if path not in image_cache:
            # 加载新图片并加入缓存
            img = pyglet.image.load(path)
            # print(f"Loading: {path}")
            image_cache[path] = img
            # 清理超出缓存的旧图片
            while len(image_cache) > MAX_IMAGES:
                oldest_path, oldest_img = image_cache.popitem(last=False)
                oldest_texture = oldest_img.get_texture()
                oldest_texture.delete()  # 显式删除纹理
                # print(f"Removed from cache: {oldest_path}")
        else:
            print(f"Using cached: {path}")
        
        # 确保缓存顺序更新
        image_cache.move_to_end(path)
        
        # 创建新Sprite
        new_sprite = pyglet.sprite.Sprite(image_cache[path], batch=self.batch)
        self.scale_to_fit(new_sprite, window.width, window.height)
        self.center_sprite(new_sprite, window.width, window.height)
        
        # 清理之前的next_img
        if self.next_img:
            self.next_img.delete()
        
        self.next_img = new_sprite

    def scale_to_fit(self, sprite, max_width, max_height):
        scale = min(max_width / sprite.width, max_height / sprite.height)
        sprite.update(scale=scale)

    def center_sprite(self, sprite, max_width, max_height):
        sprite.x = (max_width - sprite.width) // 2
        sprite.y = (max_height - sprite.height) // 2

    def transition(self, dt):
        if self.transitioning or not self.next_img:
            return
        
        self.transitioning = True
        self.animation_start_time = time.time()
        
        # 记录旧Sprite并启动动画
        if self.current:
            self.old_img = self.current
            self.old_img.opacity = 255
        
        # 随机选择动画效果
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
            # 删除旧Sprite
            if self.old_img:
                self.old_img.delete()
                self.old_img = None

    def fade_out_old(self, dt):
        if self.old_img:
            elapsed = time.time() - self.animation_start_time
            progress = min(elapsed / TRANSITION, 1.0)
            eased_progress = ease_out_quad(progress)
            self.old_img.opacity = int(255 * (1 - eased_progress))
            
            if progress >= 1.0:
                clock.unschedule(self.fade_out_old)
                # 此处不需要手动删除old_img，已在slide_left处理

slides = SlideShow()
slides.load_next()

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

def update(dt):
    slides.load_next()
    slides.transition(dt)

pyglet.clock.schedule_interval(update, DURATION)
pyglet.app.run()
