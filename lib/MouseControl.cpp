#include <windows.h>

extern "C" {
    __declspec(dllexport) void move_R(int delta_x, int delta_y);
    __declspec(dllexport) void click_Left_down();
    __declspec(dllexport) void click_Left_up();
}

// 移动
void move_R(int delta_x, int delta_y) {
    //使用mouse_event
    mouse_event(MOUSEEVENTF_MOVE, delta_x, delta_y, 0, 0);
}

// 按下
void click_Left_down() {
    mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0);
}

// 松开
void click_Left_up() {
    mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0);
}

// 入口点
BOOL APIENTRY DllMain(HMODULE hModule, DWORD ul_reason_for_call, LPVOID lpReserved) {
    switch (ul_reason_for_call) {
    case DLL_PROCESS_ATTACH:
    case DLL_THREAD_ATTACH:
    case DLL_THREAD_DETACH:
    case DLL_PROCESS_DETACH:
        break;
    }
    return TRUE;
} 