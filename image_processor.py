import os
from PIL import Image, ImageFilter
import pyglet
import threading
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from config import *  # 导入配置变量

image_cache = OrderedDict()

# 缩略图相关的全局变量
thumbnail_cache = {}
thumbnail_data_cache = {}
thumbnail_executor = ThreadPoolExecutor(max_workers=THREAD_POOL_SIZE)
thumbnail_lock = threading.Lock()
pending_thumbnail_tasks = []

def apply_sharpening(img_path, window_width, window_height):
    """应用锐化效果到图片（包含重采样优化版）"""
    sharpened = None
    img_data = None
    resampled_img = None
    
    try:
        # 使用上下文管理器确保PIL资源正确释放
        with Image.open(img_path).convert('RGBA') as pil_img:
            # 先进行重采样优化（使用LANCZOS算法）
            # 计算缩放比例，保持图片原始宽高比
            scale_x = window_width / pil_img.width
            scale_y = window_height / pil_img.height
            scale = min(scale_x, scale_y)
            
            new_width = int(pil_img.width * scale)
            new_height = int(pil_img.height * scale)
            
            # 使用LANCZOS重采样算法进行高质量缩放
            resampled_img = pil_img.resize((new_width, new_height), Image.Resampling.LANCZOS)
            
            # 在重采样后的图片上应用锐化滤镜
            sharpened = resampled_img.filter(ImageFilter.UnsharpMask(radius=1.5, percent=60, threshold=3))

            # 立即释放resampled_img对象
            resampled_img.close() if hasattr(resampled_img, 'close') else None
            del resampled_img
            resampled_img = None

            # # 转换为RGBA模式（确保透明度支持）
            # if sharpened.mode != 'RGBA':
            #     sharpened = sharpened.convert('RGBA')
            
            # 垂直翻转图像适配pyglet坐标系
            sharpened = sharpened.transpose(Image.FLIP_TOP_BOTTOM)
            
            # 获取图片尺寸（在获取字节数据前）
            width, height = sharpened.size
            
            # 获取图片数据
            img_data = sharpened.tobytes()
            
            # 立即释放PIL对象
            sharpened.close() if hasattr(sharpened, 'close') else None
            del sharpened
            sharpened = None
            
            # 创建pyglet图像
            img = pyglet.image.ImageData(width, height, 'RGBA', img_data)
            
            # 转换为纹理
            if not isinstance(img, pyglet.image.Texture):
                img = img.get_texture()
            
            # 清理字节数据
            del img_data
            img_data = None
            
            return img
    except Exception as e:
        print(f"锐化图片失败: {img_path} - {e}")
        
        # 确保在异常情况下也能清理资源
        if sharpened is not None:
            sharpened.close() if hasattr(sharpened, 'close') else None
            del sharpened
            
        if img_data is not None:
            del img_data

        if resampled_img is not None:
            resampled_img.close() if hasattr(resampled_img, 'close') else None
            del resampled_img
        
        # 如果锐化失败，返回原始图片
        return pyglet.image.load(img_path)

def clean_cache():
    """清理图片缓存"""
    while len(image_cache) > MAX_IMAGES:
        oldest_path, oldest_img = image_cache.popitem(last=False)
        try:
            # 安全释放纹理资源
            if hasattr(oldest_img, 'get_texture'):
                texture = oldest_img.get_texture()
                if texture:
                    texture.delete()
                    print(f"清理GPU缓存完成")

            # 解除所有引用
            del oldest_img
           
        except Exception as e:
            print(f"清理缓存时出错: {e}")

# 缩略图相关函数
def generate_thumbnail_data(path):
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

def create_thumbnail_sprite_from_data(data):
    """ 在主线程创建缩图精灵 """
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

def generate_thumbnail_page(images, start_index, window_width, window_height, ready_callback=None):
    """ 生成缩略图页面（多线程版） """
    total = len(images)
    end_index = min(start_index + 10, total)
    page_key = (start_index, window_width, window_height)
    
    with thumbnail_lock:
        if page_key in thumbnail_cache:
            return thumbnail_cache[page_key]

        # 创建有效的透明占位符
        placeholder_img = pyglet.image.ImageData(1, 1, 'RGBA', b'\x00\x00\x00\x00')
        sprites = []
        for idx in range(start_index, end_index):
            path = images[idx]
            if path in thumbnail_data_cache:
                data = thumbnail_data_cache[path]
                sprites.append(create_thumbnail_sprite_from_data(data))
            else:
                future = thumbnail_executor.submit(generate_thumbnail_data, path)
                if ready_callback:
                    future.add_done_callback(lambda f, idx=idx: ready_callback(f, start_index, idx))
                pending_thumbnail_tasks.append(future)
                # 创建临时占位精灵
                placeholder = pyglet.sprite.Sprite(placeholder_img)
                placeholder.width = THUMBNAIL_SIZE[0]
                placeholder.height = THUMBNAIL_SIZE[1]
                sprites.append(placeholder)

        thumbnail_cache[page_key] = sprites
        return thumbnail_cache[page_key]

def cleanup_thumbnails():
    """清理所有缩略图资源"""
    def do_cleanup():
        with thumbnail_lock:
            # print(f"DEBUG: 开始清理缩略图，缓存大小: {len(thumbnail_cache)}")
            if not pyglet.gl.current_context:  # 关键检查
                print("OpenGL 上下文已销毁，跳过清理")
                return
            # 终止进行中的任务
            for task in pending_thumbnail_tasks:
                if not task.done():
                    task.cancel()
            pending_thumbnail_tasks.clear()

            # 清空数据缓存
            thumbnail_data_cache.clear()

            # 释放所有缩略图精灵
            deleted_count = 0
            for page in thumbnail_cache.values():
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
                            # 解除图像引用，使用这个会有NoneType错误输出，使用下面的delete方法可以避免
                            sprite.image = None

                        # 删除精灵本身
                        # if hasattr(sprite, 'delete'):
                        #     sprite.delete()
                        #     deleted_count += 1
                        #     print(f"删除缩略图 sprite : {deleted_count}")
                            
                    except AttributeError as e:
                        if "'NoneType'" in str(e):  # 忽略None相关错误
                            pass
                    except Exception as e:
                        print(f"安全清理失败: {str(e)[:50]}...")  # 截短错误信息
                    
            # 清空缓存
            thumbnail_cache.clear()
    
    return do_cleanup
