"""
STDIO Device - Simple console I/O device simulation

提供一个简单的控制台输出设备：
- 往指定地址写入字符会输出到控制台
- 用于多线程/多域环境下的调试输出
"""

from typing import Optional, Callable


class StdioDevice:
    """
    简单的控制台输出设备

    内存映射：
    - base_addr + 0x00: 输出寄存器（写入字符输出到控制台）
    - base_addr + 0x04: 控制寄存器（可选，用于刷新等）

    使用示例：
        stdio = StdioDevice(base_addr=0xFFFF0000)
        stdio.write_byte(0xFFFF0000, ord('A'))  # 输出 'A'
    """

    def __init__(self, base_addr: int, size: int = 0x1000,
                 output_callback: Optional[Callable[[str], None]] = None):
        """
        初始化 STDIO 设备

        Args:
            base_addr: 设备基地址
            size: 设备地址空间大小，默认 4KB
            output_callback: 自定义输出回调，默认为 print
        """
        self.base_addr = base_addr
        self.size = size
        self.output_callback = output_callback or print

        # 缓冲区，用于累积输出
        self._buffer: list = []

    def contains(self, addr: int) -> bool:
        """检查地址是否在设备范围内"""
        return self.base_addr <= addr < self.base_addr + self.size

    def read_byte(self, addr: int) -> int:
        """读取字节（设备只支持输出，读取返回 0）"""
        if not self.contains(addr):
            raise MemoryError(f"Address 0x{addr:08x} not in STDIO device range")
        return 0

    def write_byte(self, addr: int, value: int) -> None:
        """写入字节，输出字符到控制台"""
        if not self.contains(addr):
            raise MemoryError(f"Address 0x{addr:08x} not in STDIO device range")

        offset = addr - self.base_addr

        if offset == 0x00:
            # 输出寄存器
            char = chr(value & 0xFF)
            self.output_callback(char)
        elif offset == 0x04:
            # 控制寄存器
            if value == 1:  # 刷新缓冲区
                self.flush()

    def read_word(self, addr: int) -> int:
        """读取字（设备只支持输出，读取返回 0）"""
        if not self.contains(addr):
            raise MemoryError(f"Address 0x{addr:08x} not in STDIO device range")
        return 0

    def write_word(self, addr: int, value: int) -> None:
        """写入字，输出字符到控制台"""
        if not self.contains(addr):
            raise MemoryError(f"Address 0x{addr:08x} not in STDIO device range")

        offset = addr - self.base_addr

        if offset == 0x00:
            # 输出寄存器 - 输出低字节
            char = chr(value & 0xFF)
            self.output_callback(char)
        elif offset == 0x04:
            # 控制寄存器
            if value == 1:  # 刷新缓冲区
                self.flush()

    def flush(self) -> None:
        """刷新输出缓冲区"""
        pass  # print 自带刷新，这里可以扩展

    def write_string(self, s: str) -> None:
        """直接输出字符串（用于测试）"""
        self.output_callback(s)

    def __repr__(self) -> str:
        return f"StdioDevice(base=0x{self.base_addr:08x}, size=0x{self.size:x})"


class StdioDeviceManager:
    """
    STDIO 设备管理器

    支持多个 STDIO 设备，用于不同 Domain 的输出
    """

    def __init__(self):
        self.devices: dict = {}  # addr -> StdioDevice

    def register(self, device: StdioDevice) -> None:
        """注册设备"""
        self.devices[device.base_addr] = device

    def unregister(self, base_addr: int) -> None:
        """注销设备"""
        if base_addr in self.devices:
            del self.devices[base_addr]

    def find_device(self, addr: int) -> Optional[StdioDevice]:
        """查找地址对应的设备"""
        for device in self.devices.values():
            if device.contains(addr):
                return device
        return None

    def read_byte(self, addr: int) -> Optional[int]:
        """尝试读取字节，如果地址不在任何设备中返回 None"""
        device = self.find_device(addr)
        if device:
            return device.read_byte(addr)
        return None

    def write_byte(self, addr: int, value: int) -> bool:
        """尝试写入字节，成功返回 True"""
        device = self.find_device(addr)
        if device:
            device.write_byte(addr, value)
            return True
        return False

    def read_word(self, addr: int) -> Optional[int]:
        """尝试读取字，如果地址不在任何设备中返回 None"""
        device = self.find_device(addr)
        if device:
            return device.read_word(addr)
        return None

    def write_word(self, addr: int, value: int) -> bool:
        """尝试写入字，成功返回 True"""
        device = self.find_device(addr)
        if device:
            device.write_word(addr, value)
            return True
        return False