import os
import subprocess
from glob import glob
import math

# 条件导入psutil
try:
    import psutil
    PSUTIL_AVAILABLE = True
    process = psutil.Process()
except ImportError:
    PSUTIL_AVAILABLE = False
    print("警告: psutil未安装，内存监控功能将被禁用")

def print_memory(slides=None, image_cache=None):
    """打印详细的内存使用情况并执行内存清理"""
    if not PSUTIL_AVAILABLE:
        return
        
    try:
 
        # 获取当前进程的内存信息
        mem_info = process.memory_info()
        vms = mem_info.vms / 1024 / 1024  # 虚拟内存 (MB)
        rss = mem_info.rss / 1024 / 1024   # 物理内存 (MB)
        
        # 获取系统内存信息
        system_mem = psutil.virtual_memory()
        available = system_mem.available / 1024 / 1024  # 可用内存 (MB)
        
        # 统计缓存和纹理
        textures = 0
        valid_images = 0
        
        # 如果有image_cache参数，统计纹理
        if image_cache:
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
        
        # 统计缩略图缓存
        thumbnail_cache_size = 0
        thumbnail_data_size = 0
        if slides and hasattr(slides, 'thumbnail_cache'):
            thumbnail_cache_size = len(slides.thumbnail_cache)
        if slides and hasattr(slides, 'thumbnail_data_cache'):
            thumbnail_data_size = len(slides.thumbnail_data_cache)
        
        # 计算估算的纹理内存 (假设每个纹理平均10MB)
        estimated_texture_mem = textures * 10
        
        print(f"=== 内存使用情况 ===")
        print(f"虚拟内存: {vms:.2f} MB | 物理内存: {rss:.2f} MB")
        print(f"系统可用内存: {available:.2f} MB")
        if image_cache:
            print(f"图片缓存: {valid_images}/{len(image_cache)} | 活跃纹理: {textures}")
        print(f"缩略图缓存: {thumbnail_cache_size} | 缩略图数据: {thumbnail_data_size}")
        if textures > 0:
            print(f"估算纹理内存: {estimated_texture_mem} MB")
        
            
    except Exception as e:
        print(f"内存监控出错: {e}")

def debug_gc_collect(location):
    """带调试信息的GC调用"""
    import gc
    before = gc.get_count()
    reclaimed = gc.collect()
    after = gc.get_count()
    print(f"[{location}] GC回收了{reclaimed}个对象，计数: {before} -> {after}")



def choose_folder():
    """返回选择的路径，取消选择时返回None"""
    script = '''
    tell application "System Events"
        activate
        try
            set selectedFolder to POSIX path of (choose folder with prompt "请选择图片目录")
            return selectedFolder
        on error
            return "cancel"
        end try
    end tell
    '''
    try:
        result = subprocess.check_output(['osascript', '-e', script], 
                                       stderr=subprocess.STDOUT,
                                       universal_newlines=True).strip()
        return result if result != "cancel" else None
    except subprocess.CalledProcessError as e:
        print(f"文件夹选择出错: {e.output}")
        return None

def validate_folder(path):
    """验证目录是否包含图片"""
    if not path or not os.path.isdir(path):
        return False
    try:
        return any(f.lower().endswith(('.png', '.jpg', '.jpeg', '.webp'))
                for f in glob(os.path.join(path, '**/*.*'), recursive=True))
    except Exception as e:
        print(f"目录扫描错误: {e}")
        return False

def ease_out_quad(t):
    return t * (2 - t)

def ease_out_cubic(t):
    return 1 - (1 - t)**3
    
def ease_out_sine(t):
    return math.sin(t * math.pi / 2)

def open_file_in_finder(file_path):
    """ 使用macOS的open命令打开文件所在文件夹并选中文件 """
    try:
        subprocess.run(['open', '-R', file_path], check=True)
    except subprocess.CalledProcessError as e:
        print(f"打开文件夹失败: {e}")
    except Exception as e:
        print(f"发生意外错误: {e}")