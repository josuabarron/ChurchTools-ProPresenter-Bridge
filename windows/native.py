"""Windows WinMM input and per-user DPAPI token storage; no third-party driver code."""
import ctypes as C
from ctypes import wintypes as W
import os
from core import BridgeError, note_on


class Midi:
    def __init__(self):
        if os.name != 'nt':
            raise BridgeError('MIDI-Eingang benötigt Windows.')
        self.dll = C.WinDLL('winmm')
        self.handle = W.HANDLE()
        self.callback_type = C.WINFUNCTYPE(None, W.HANDLE, W.UINT, C.c_size_t, C.c_size_t, C.c_size_t)
        self.dll.midiInOpen.argtypes = [C.POINTER(W.HANDLE), W.UINT, self.callback_type, C.c_size_t, W.DWORD]
        self.dll.midiInOpen.restype = W.UINT
        for name in ('midiInStart', 'midiInStop', 'midiInReset', 'midiInClose'):
            getattr(self.dll, name).argtypes = [W.HANDLE]
            getattr(self.dll, name).restype = W.UINT
        self.dll.midiInGetNumDevs.restype = W.UINT
        self.dll.midiInGetDevCapsW.argtypes = [C.c_size_t, C.c_void_p, W.UINT]
        self.dll.midiInGetDevCapsW.restype = W.UINT
        self.callback = None

    @staticmethod
    def check(code):
        if code:
            raise BridgeError(f'Windows MIDI-Fehler {code}. Port und loopMIDI prüfen.')

    def devices(self):
        class Caps(C.Structure):
            _fields_ = [('mid', W.WORD), ('pid', W.WORD), ('version', W.UINT),
                        ('name', W.WCHAR * 32), ('support', W.DWORD)]
        result = []
        for index in range(self.dll.midiInGetNumDevs()):
            caps = Caps()
            self.check(self.dll.midiInGetDevCapsW(index, C.byref(caps), C.sizeof(caps)))
            result.append((index, caps.name))
        return result

    def open(self, device, channel, receive):
        self.close()
        def callback(handle, message, instance, packed, timestamp):
            if message == 0x3C3:  # MIM_DATA: only enqueue, never perform I/O in this callback.
                note = note_on(packed, channel)
                if note is not None:
                    receive(note)
        self.callback = self.callback_type(callback)  # Keep delegate alive until midiInClose.
        self.check(self.dll.midiInOpen(C.byref(self.handle), device, self.callback, 0, 0x30000))
        try:
            self.check(self.dll.midiInStart(self.handle))
        except Exception:
            self.close()
            raise

    def close(self):
        if self.handle.value:
            self.dll.midiInStop(self.handle)
            self.dll.midiInReset(self.handle)
            self.check(self.dll.midiInClose(self.handle))
            self.handle = W.HANDLE()
        self.callback = None


def protect(data, decrypt=False):
    if os.name != 'nt':
        raise BridgeError('Tokenspeicherung benötigt Windows DPAPI.')
    class Blob(C.Structure):
        _fields_ = [('size', W.DWORD), ('data', C.POINTER(C.c_ubyte))]
    buffer = (C.c_ubyte * len(data)).from_buffer_copy(data)
    source, output = Blob(len(data), buffer), Blob()
    dll = C.WinDLL('crypt32', use_last_error=True)
    function = dll.CryptUnprotectData if decrypt else dll.CryptProtectData
    function.argtypes = [C.POINTER(Blob), C.c_void_p, C.c_void_p, C.c_void_p,
                         C.c_void_p, W.DWORD, C.POINTER(Blob)]
    function.restype = W.BOOL
    if not function(C.byref(source), None, None, None, None, 1, C.byref(output)):
        raise BridgeError('Windows konnte den Token nicht entschlüsseln/speichern. Token neu eingeben.')
    kernel = C.WinDLL('kernel32')
    kernel.LocalFree.argtypes = [C.c_void_p]
    kernel.LocalFree.restype = C.c_void_p
    try:
        return C.string_at(output.data, output.size)
    finally:
        kernel.LocalFree(output.data)
