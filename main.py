from loguru import logger
import ctypes
import cv2
import numpy as np
import win32gui
import win32api
from mss import mss
import threading
import os
import keyboard
import time

from utils.logServer import logServer

class AimLabAutoAim:
    def __init__(self):
        # 动态获取屏幕分辨率
        screen_width = win32api.GetSystemMetrics(0)  # 屏幕宽度
        screen_height = win32api.GetSystemMetrics(1)  # 屏幕高度
        logger.debug(f"屏幕分辨率: {screen_width}x{screen_height}")
        
        # 初始化鼠标控制驱动
        dll_path = os.path.join(os.path.dirname(__file__), 'lib', 'MouseControl.dll')
        logger.debug(f"加载DLL: {dll_path}")
        if not os.path.exists(dll_path):
            logger.error(f"鼠标控制DLL文件不存在: {dll_path}")
            raise FileNotFoundError(f"找不到鼠标控制DLL文件: {dll_path}")
        
        try:
            self.driver = ctypes.CDLL(dll_path)
            logger.debug("鼠标控制驱动加载成功")
        except Exception as e:
            logger.error(f"加载鼠标控制驱动失败: {e}")
            raise
        
        # 全局变量
        self.controlling_mouse = False
        self.detection_thread = None
        self.target_hwnd = None  # 改为通用的目标窗口句柄
        self.current_window_title = ""  # 当前窗口标题
        self.middle_left = 0
        self.middle_top = 0
        self.running = True  # 程序运行状态
        
        # 检测区域占屏幕的比例
        detection_ratio = 0.7
        self.region_width = int(screen_width * detection_ratio)
        self.region_height = int(screen_height * detection_ratio)
        
        # 确保检测区域不小于最小值，不大于最大值
        min_region = 400
        max_region_width = int(screen_width * 0.95)  # 最大95%屏幕宽度
        max_region_height = int(screen_height * 0.95)  # 最大95%屏幕高度
        
        self.region_width = max(min_region, min(self.region_width, max_region_width))
        self.region_height = max(min_region, min(self.region_height, max_region_height))
        
        logger.debug(f"计算得出检测区域: {self.region_width}x{self.region_height}")
        
        self.lower_color = np.array([85, 210, 80])  # HSV下限
        self.upper_color = np.array([95, 245, 255])  # HSV上限
        self.threshold = 14  # 瞄准阈值
        
        logger.debug("初始化完成")

    class BoxInfo:
        def __init__(self, box, distance):
            self.box = box
            self.distance = distance

    def capture_screen(self):
        """截取当前活动窗口的指定区域"""
        # 获取当前前台窗口
        current_foreground = win32gui.GetForegroundWindow()
        
        # 如果窗口句柄改变了，更新目标窗口
        if self.target_hwnd != current_foreground:
            self.target_hwnd = current_foreground
            if self.target_hwnd != 0:
                self.current_window_title = win32gui.GetWindowText(self.target_hwnd)
                logger.info(f"切换到新窗口: '{self.current_window_title}'")
            else:
                logger.warning("未找到活动窗口")
                return None

        try:
            # 获取窗口的客户区域大小
            left, top, right, bottom = win32gui.GetClientRect(self.target_hwnd)
            client_width = right - left
            client_height = bottom - top

            # 计算中间区域的坐标
            self.middle_left = client_width // 2 - self.region_width // 2
            self.middle_top = client_height // 2 - self.region_height // 2

            # 将客户区域的左上角坐标转换为屏幕坐标
            client_left, client_top = win32gui.ClientToScreen(
                self.target_hwnd, (self.middle_left, self.middle_top)
            )

            # 使用 mss 截取指定区域
            with mss() as sct:
                monitor = {
                    "left": client_left, 
                    "top": client_top, 
                    "width": self.region_width, 
                    "height": self.region_height
                }
                img = sct.grab(monitor)
                frame = np.array(img)
                frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)
                return frame
                
        except Exception as e:
            logger.error(f"截屏失败: {e}")
            return None

    def detect_ball(self, frame):
        """检测目标小球"""
        try:
            # 转换到 HSV 空间
            hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
            
            # 根据颜色范围创建掩码
            mask = cv2.inRange(hsv, self.lower_color, self.upper_color)
            
            # 查找轮廓
            contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            
            # 计算最近的目标
            closest_box_info = None
            closest_distance = float('inf')
            screen_center_x = frame.shape[1] // 2
            screen_center_y = frame.shape[0] // 2
            
            for contour in contours:
                # 获取轮廓的边界框
                x, y, w, h = cv2.boundingRect(contour)
                center_x = (x + x + w) // 2
                center_y = (y + y + h) // 2
                distance = ((center_x - screen_center_x) ** 2 + (center_y - screen_center_y) ** 2) ** 0.5
                
                if distance < closest_distance:
                    closest_box_info = self.BoxInfo((x, y, x + w, y + h), distance)
                    closest_distance = distance
            
            return closest_box_info
            
        except Exception as e:
            logger.error(f"目标检测失败: {e}")
            return None

    def move_mouse_by(self, delta_x, delta_y):
        """相对移动鼠标"""
        try:
            self.driver.move_R(int(delta_x), int(delta_y))
        except Exception as e:
            logger.error(f"鼠标移动失败: {e}")

    def click_mouse(self):
        """点击鼠标左键"""
        try:
            self.driver.click_Left_down()
            self.driver.click_Left_up()
            logger.debug("执行点击")
        except Exception as e:
            logger.error(f"鼠标点击失败: {e}")

    def run_detection(self):
        """运行检测和自动瞄准的主循环"""
        logger.info("开始")
        previous_vector_x = 0
        previous_vector_y = 0
        moved_count = 0
        max_moved_count = 8

        while self.controlling_mouse and self.running:
            try:
                frame = self.capture_screen()
                if frame is None:
                    time.sleep(0.01)  # 稳定调整
                    continue

                # 检测小球
                closest_box_info = self.detect_ball(frame)

                if closest_box_info:
                    # 计算屏幕中心到最近目标的向量
                    target_x_frame = (closest_box_info.box[0] + closest_box_info.box[2]) // 2
                    target_y_frame = (closest_box_info.box[1] + closest_box_info.box[3]) // 2
                    vector_x = target_x_frame - frame.shape[1] // 2
                    vector_y = target_y_frame - frame.shape[0] // 2

                    if closest_box_info.distance > self.threshold:
                        # 移动鼠标到目标
                        step_controller = 1
                        self.move_mouse_by(vector_x * step_controller, vector_y * step_controller)
                        logger.debug(f"移动鼠标: ({vector_x * step_controller}, {vector_y * step_controller})")
                    else:
                        # 距离足够近执行点击
                        self.click_mouse()
                        logger.debug("检测到目标，执行点击")

                    # 更新向量
                    previous_vector_x = vector_x
                    previous_vector_y = vector_y
                    moved_count = 0
                else:
                    # 没有检测到目标反向移动
                    if previous_vector_x != 0 or previous_vector_y != 0:
                        if moved_count < max_moved_count:
                            self.move_mouse_by(-previous_vector_x, -previous_vector_y)
                            moved_count += 1
                
                time.sleep(0.001)
                            
            except Exception as e:
                logger.error(f"检测循环中发生错误: {e}")
                
        logger.info("检测停止")

    def start_detection(self):
        """开始检测"""
        if not self.controlling_mouse:
            self.controlling_mouse = True
            self.detection_thread = threading.Thread(target=self.run_detection, daemon=True)
            self.detection_thread.start()
            logger.info("已启动")
            return True
        else:
            logger.warning("已在运行中")
            return False

    def stop_detection(self):
        """停止检测"""
        if self.controlling_mouse:
            self.controlling_mouse = False
            if self.detection_thread and self.detection_thread.is_alive():
                self.detection_thread.join(timeout=2.0)
            logger.info("瞄准停止")
            return True
        else:
            logger.warning("自动瞄准未在运行")
            return False

    def adjust_color_detection(self):
        """调整颜色检测范围"""
        logger.info("启动颜色检测调整工具")
        
        # 创建调整窗口
        cv2.namedWindow('Color Adjustment')
        
        # 创建滑块
        cv2.createTrackbar('Lower Hue', 'Color Adjustment', self.lower_color[0], 179, lambda x: None)
        cv2.createTrackbar('Lower Sat', 'Color Adjustment', self.lower_color[1], 255, lambda x: None)
        cv2.createTrackbar('Lower Val', 'Color Adjustment', self.lower_color[2], 255, lambda x: None)
        cv2.createTrackbar('Upper Hue', 'Color Adjustment', self.upper_color[0], 179, lambda x: None)
        cv2.createTrackbar('Upper Sat', 'Color Adjustment', self.upper_color[1], 255, lambda x: None)
        cv2.createTrackbar('Upper Val', 'Color Adjustment', self.upper_color[2], 255, lambda x: None)
        
        logger.info("按'S'键保存并退出，按'W'键直接退出")
        
        while True:
            frame = self.capture_screen()
            if frame is None:
                time.sleep(0.1)
                continue
                
            # 获取滑块值
            lower_h = cv2.getTrackbarPos('Lower Hue', 'Color Adjustment')
            lower_s = cv2.getTrackbarPos('Lower Sat', 'Color Adjustment')
            lower_v = cv2.getTrackbarPos('Lower Val', 'Color Adjustment')
            upper_h = cv2.getTrackbarPos('Upper Hue', 'Color Adjustment')
            upper_s = cv2.getTrackbarPos('Upper Sat', 'Color Adjustment')
            upper_v = cv2.getTrackbarPos('Upper Val', 'Color Adjustment')
            
            # 更新颜色范围
            test_lower = np.array([lower_h, lower_s, lower_v])
            test_upper = np.array([upper_h, upper_s, upper_v])
            
            # 应用颜色过滤
            hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
            mask = cv2.inRange(hsv, test_lower, test_upper)
            result = cv2.bitwise_and(frame, frame, mask=mask)
            
            # 显示结果
            cv2.imshow('Color Adjustment', result)
            
            # 检测按键 - 仿照全局键盘监听逻辑
            key = cv2.waitKey(1) & 0xFF
            if key == ord('s') or key == ord('S'):  # 按'S'键保存并退出
                # 保存新的颜色范围
                self.lower_color = test_lower
                self.upper_color = test_upper
                logger.info(f"颜色范围已更新: Lower={self.lower_color}, Upper={self.upper_color}")
                break
            elif key == ord('w') or key == ord('W'):  # 按'W'键直接退出
                logger.info("已取消颜色调整")
                break
        
        cv2.destroyWindow('Color Adjustment')

    def exit_program(self):
        """退出程序"""
        logger.info("正在退出")
        self.running = False
        self.stop_detection()
        cv2.destroyAllWindows()
        logger.info("退出")

def setup_keyboard_controls(auto_aim):
    """设置键盘控制"""
    def on_q_pressed():
        auto_aim.start_detection()
    
    def on_e_pressed():
        auto_aim.stop_detection()
    
    def on_f1_pressed():
        auto_aim.adjust_color_detection()
    
    def on_esc_pressed():
        auto_aim.exit_program()
    
    # 注册热键
    keyboard.add_hotkey('q', on_q_pressed)
    keyboard.add_hotkey('e', on_e_pressed)
    keyboard.add_hotkey('f1', on_f1_pressed)
    keyboard.add_hotkey('esc', on_esc_pressed)
    
    logger.debug("键盘驱动加载")

def main():
    """主函数"""
    # 配置日志
    log_server = logServer()
    log_server.set_config(file_log_level="DEBUG", console_log_level="DEBUG")
    

    logger.info("说明:")
    logger.info("  Q键 - 开启")
    logger.info("  E键 - 关闭")
    logger.info("  ESC键 - 退出程序")
    logger.info("  F1键 - 调整颜色检测范围")
    logger.info("")
    logger.info("程序会自动捕获当前活动窗口")
    logger.info("等待按键控制...")
    
    try:
        # 创建自动瞄准实例
        auto_aim = AimLabAutoAim()
        
        # 设置键盘控制
        setup_keyboard_controls(auto_aim)
        
        # 保持程序运行
        while auto_aim.running:
            time.sleep(0.1)
            
    except KeyboardInterrupt:
        logger.info("收到中断")
    except Exception as e:
        logger.error(f"程序运行出错: {e}")
    finally:
        logger.info("=====================结束=====================")

if __name__ == "__main__":
    main()

