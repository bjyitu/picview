import os
import sys
import pyglet
from pyglet.window import key, mouse
from glob import glob
import random
from config import *      
from utils import *      
from slideshow import SlideShow  


# 初始化窗口
config = pyglet.gl.Config(
    double_buffer=True,
    sample_buffers=1,
    samples=4
)
window = pyglet.window.Window(config=config, width=900, height=600, resizable=True, style="None", vsync=True)

# 强制选择目录
FOLDER = None
while not FOLDER:
    if os.path.exists(DEFAULT_FOLDER) and validate_folder(DEFAULT_FOLDER):
        FOLDER = DEFAULT_FOLDER
        print(f"使用默认图片目录: {DEFAULT_FOLDER}")
    else:
        print("正在弹出目录选择窗口...")
        selected = choose_folder()
        print("用户选择的目录:", selected)
        if selected and validate_folder(selected):
            FOLDER = selected
        else:
            print("请选择包含图片的有效目录")

# 加载图片
images = [f for f in glob(os.path.join(FOLDER, '**/*.*'), recursive=True)
          if f.lower().endswith(('.png', '.jpg', '.jpeg', '.webp'))]
random.shuffle(images)

if not images:
    print("目录中未找到有效图片，程序退出")
    exit(1)

# 初始化 SlideShow
slides = SlideShow(images, window)
slides.current = slides.draw_sigle_pic(images[0])
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
         # 新增1键处理
        elif symbol == key._1 and slides.manual_mode :
            if images and 0 <= slides.current_index < len(images):
                current_path = images[slides.current_index]
                if os.path.exists(current_path):
                    open_file_in_finder(current_path)
                else:
                    print(f"文件不存在: {current_path}")

@window.event
def on_close():
    # 停止所有时钟事件
    pyglet.clock.unschedule(update)
    pyglet.clock.unschedule(slides.slide_left)
    pyglet.clock.unschedule(slides.fade_out_old)
    
    # 清理缩略图资源,安全清空缓存
    def safe_clear():
        slides._cleanup_thumbnails()
        from image_processor import image_cache, thumbnail_data_cache, thumbnail_cache
        image_cache.clear()
        thumbnail_data_cache.clear()
        thumbnail_cache.clear()
        # 强制垃圾回收
        import gc
        gc.collect()

    pyglet.clock.schedule_once(safe_clear, 0)
    
    # 立即关闭窗口
    window.close()
    pyglet.app.exit()
    return True  # 阻止默认关闭流程

def update(dt):
    if not slides.manual_mode and not slides.thumbnail_mode:
        slides.load_next()
        slides.transition(dt)
        window.invalid = True

pyglet.clock.schedule_interval(update, DURATION)

# 如果启用了内存监控，每60秒打印一次内存使用情况
from utils import PSUTIL_AVAILABLE, print_memory
from image_processor import image_cache

if MEMORY_MONITORING and PSUTIL_AVAILABLE:
    def memory_monitor(dt):
        debug_gc_collect("memory_monitor")
        print_memory(slides, image_cache)
    
    pyglet.clock.schedule_interval(memory_monitor, 60)

pyglet.app.run()
