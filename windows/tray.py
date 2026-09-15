"""Infobereich-Symbol („Tray") für die Bridge – reines Win32, keine Zusatzpakete.

Auf einen Blick erkennbar, ob die Bridge arbeitet:

    grün   Bridge läuft
    grau   Bridge gestoppt oder Fehler

Links-Doppelklick öffnet das Fenster, Rechtsklick zeigt das Menü.

Warum ctypes statt pystray: das Projekt setzt bereits in native.py auf Win32 über
ctypes. Ein zusätzliches Paket brächte nur eine weitere Abhängigkeit in den
Einzeldatei-Build, ohne mehr zu leisten.
"""
import ctypes as C
from ctypes import wintypes as W
import sys
from pathlib import Path

LRESULT = C.c_ssize_t
WNDPROC = C.WINFUNCTYPE(LRESULT, W.HWND, W.UINT, W.WPARAM, W.LPARAM)

WM_NULL = 0x0000
WM_DESTROY = 0x0002
WM_LBUTTONUP = 0x0202
WM_LBUTTONDBLCLK = 0x0203
WM_RBUTTONUP = 0x0205

NIM_ADD = 0x00000000
NIM_MODIFY = 0x00000001
NIM_DELETE = 0x00000002

NIF_MESSAGE = 0x00000001
NIF_ICON = 0x00000002
NIF_TIP = 0x00000004
NIF_INFO = 0x00000010

NIIF_INFO = 0x00000001

IMAGE_ICON = 1
LR_LOADFROMFILE = 0x0010

SM_CXSMICON, SM_CYSMICON = 49, 50

MF_STRING = 0x00000000
MF_SEPARATOR = 0x00000800
MF_GRAYED = 0x00000001
TPM_RIGHTBUTTON = 0x0002
TPM_RETURNCMD = 0x0100

ERROR_ALREADY_EXISTS = 183
HWND_BROADCAST = 0xFFFF
SYNCHRONIZE = 0x00100000

# Eigene Fenster-Nachrichten: RegisterWindowMessageW liefert für dieselbe
# Zeichenkette systemweit dieselbe Nummer. So verständigen sich zwei getrennte
# Prozesse, ohne dass Daten ausgetauscht werden müssen.
QUIT_MESSAGE_NAME = 'ChurchToolsBridge:Quit'
SHOW_MESSAGE_NAME = 'ChurchToolsBridge:Show'
# Solange eine Bridge läuft, hält sie diesen Mutex. Er verschwindet mit dem
# Prozess – auch nach einem Absturz.
MUTEX_NAME = 'Local\\ChurchToolsBridge-NurEine'


def _user32():
    return C.WinDLL('user32', use_last_error=True)


def registered_message(name):
    """Systemweit gleiche Nummer für eine eigene Fenster-Nachricht."""
    user32 = _user32()
    user32.RegisterWindowMessageW.restype = W.UINT
    user32.RegisterWindowMessageW.argtypes = [W.LPCWSTR]
    return int(user32.RegisterWindowMessageW(name)) or 0


def announce(name):
    """Schickt eine Nachricht an eine laufende Bridge. True, wenn abgeschickt."""
    nummer = registered_message(name)
    if not nummer:
        return False
    user32 = _user32()
    user32.PostMessageW.restype = W.BOOL
    user32.PostMessageW.argtypes = [W.HWND, W.UINT, W.WPARAM, W.LPARAM]
    return bool(user32.PostMessageW(HWND_BROADCAST, nummer, 0, 0))


def ask_to_quit():
    """Bittet eine laufende Bridge zu beenden – sie räumt ihr Symbol selbst weg."""
    return announce(QUIT_MESSAGE_NAME)


def ask_to_show():
    """Bittet eine laufende Bridge, ihr Fenster zu zeigen."""
    return announce(SHOW_MESSAGE_NAME)


class Instance:
    """Sorgt dafür, dass die Bridge nur einmal läuft.

    Ohne das entstünde beim Doppelklick auf die Verknüpfung eine zweite Bridge:
    zwei Symbole neben der Uhr, zwei Zugriffe auf denselben MIDI-Port. Die
    zweite Instanz bittet die erste stattdessen, ihr Fenster zu zeigen.
    """

    def __init__(self, name=MUTEX_NAME):
        self.name = name
        self.handle = None
        self.kernel32 = C.WinDLL('kernel32', use_last_error=True)

    def acquire(self):
        """True, wenn diese Instanz die erste ist."""
        kernel = self.kernel32
        kernel.CreateMutexW.restype = W.HANDLE
        kernel.CreateMutexW.argtypes = [C.c_void_p, W.BOOL, W.LPCWSTR]
        C.set_last_error(0)
        self.handle = kernel.CreateMutexW(None, False, self.name)
        if not self.handle:
            return True                     # im Zweifel lieber starten
        return C.get_last_error() != ERROR_ALREADY_EXISTS

    @staticmethod
    def running(name=MUTEX_NAME):
        """Prüft, ob gerade eine Bridge läuft."""
        kernel = C.WinDLL('kernel32', use_last_error=True)
        kernel.OpenMutexW.restype = W.HANDLE
        kernel.OpenMutexW.argtypes = [W.DWORD, W.BOOL, W.LPCWSTR]
        handle = kernel.OpenMutexW(SYNCHRONIZE, False, name)
        if not handle:
            return False
        kernel.CloseHandle(handle)
        return True

    def release(self):
        if self.handle:
            self.kernel32.CloseHandle(self.handle)
            self.handle = None


def assets_dir():
    """Ordner mit den Icon-Dateien – auch im PyInstaller-Build."""
    if getattr(sys, 'frozen', False):
        basis = Path(getattr(sys, '_MEIPASS', Path(sys.executable).parent))
    else:
        basis = Path(__file__).resolve().parent
    return basis / 'assets'


class GUID(C.Structure):
    _fields_ = [('Data1', W.DWORD), ('Data2', W.WORD), ('Data3', W.WORD),
                ('Data4', C.c_ubyte * 8)]


class WNDCLASSEXW(C.Structure):
    _fields_ = [
        ('cbSize', W.UINT),
        ('style', W.UINT),
        ('lpfnWndProc', WNDPROC),
        ('cbClsExtra', C.c_int),
        ('cbWndExtra', C.c_int),
        ('hInstance', W.HINSTANCE),
        ('hIcon', W.HICON),
        ('hCursor', W.HANDLE),
        ('hbrBackground', W.HBRUSH),
        ('lpszMenuName', W.LPCWSTR),
        ('lpszClassName', W.LPCWSTR),
        ('hIconSm', W.HICON),
    ]


class NOTIFYICONDATAW(C.Structure):
    _fields_ = [
        ('cbSize', W.DWORD),
        ('hWnd', W.HWND),
        ('uID', W.UINT),
        ('uFlags', W.UINT),
        ('uCallbackMessage', W.UINT),
        ('hIcon', W.HICON),
        ('szTip', C.c_wchar * 128),
        ('dwState', W.DWORD),
        ('dwStateMask', W.DWORD),
        ('szInfo', C.c_wchar * 256),
        ('uVersion', W.UINT),
        ('szInfoTitle', C.c_wchar * 64),
        ('dwInfoFlags', W.DWORD),
        ('guidItem', GUID),
        ('hBalloonIcon', W.HICON),
    ]


def load_icon(path):
    """Lädt ein .ico passend zur Symbolgröße des Systems."""
    user32 = C.WinDLL('user32', use_last_error=True)
    cx = user32.GetSystemMetrics(SM_CXSMICON)
    user32.LoadImageW.restype = W.HICON
    user32.LoadImageW.argtypes = [W.HINSTANCE, W.LPCWSTR, W.UINT, C.c_int, C.c_int, W.UINT]
    handle = user32.LoadImageW(None, str(path), IMAGE_ICON, cx, cx, LR_LOADFROMFILE)
    return handle


class TrayIcon:
    """Ein Symbol im Infobereich mit Menü."""

    OPEN, STATUS, QUIT = 1, 2, 3
    _windows = {}

    def __init__(self, tooltip='ChurchTools Bridge', on_open=None, on_status=None, on_quit=None):
        self.tooltip = tooltip[:127]
        self.on_open = on_open
        self.on_status = on_status
        self.on_quit = on_quit
        self.online = None
        self.hwnd = None
        self.uid = 1
        self.added = False
        self._icons = {}
        self._proc = None
        self._class_atom = None
        self._taskbar_created = 0
        self._quit_message = 0
        self._show_message = 0
        self.error = None
        self.user32 = C.WinDLL('user32', use_last_error=True)
        self.shell32 = C.WinDLL('shell32', use_last_error=True)
        self.kernel32 = C.WinDLL('kernel32', use_last_error=True)

    # ---------------------------------------------------------------- Win32

    def install(self):
        """Legt Fenster und Symbol an. Rückgabe: True bei Erfolg."""
        if sys.platform != 'win32':
            self.error = 'Der Infobereich gibt es nur unter Windows.'
            return False
        try:
            self._register_window()
            self._load_icons()
            self._add_icon()
            return self.added
        except OSError as error:
            self.error = str(error)
            return False

    def _register_window(self):
        u = self.user32
        u.DefWindowProcW.restype = LRESULT
        u.DefWindowProcW.argtypes = [W.HWND, W.UINT, W.WPARAM, W.LPARAM]
        u.CreateWindowExW.restype = W.HWND
        u.CreateWindowExW.argtypes = [W.DWORD, W.LPCWSTR, W.LPCWSTR, W.DWORD,
                                      C.c_int, C.c_int, C.c_int, C.c_int,
                                      W.HWND, W.HMENU, W.HINSTANCE, W.LPVOID]
        u.RegisterClassExW.restype = W.ATOM
        u.RegisterClassExW.argtypes = [C.POINTER(WNDCLASSEXW)]
        u.DestroyWindow.argtypes = [W.HWND]

        self._taskbar_created = u.RegisterWindowMessageW('TaskbarCreated')
        self._quit_message = registered_message(QUIT_MESSAGE_NAME)
        self._show_message = registered_message(SHOW_MESSAGE_NAME)
        self._handler = WNDPROC(self._wndproc)
        klasse = 'ChurchToolsBridgeTray'
        self.hinstance = self.kernel32.GetModuleHandleW(None)
        wndclass = WNDCLASSEXW()
        wndclass.cbSize = C.sizeof(WNDCLASSEXW)
        wndclass.lpfnWndProc = self._handler
        wndclass.hInstance = self.hinstance
        wndclass.lpszClassName = klasse
        self._class_atom = u.RegisterClassExW(C.byref(wndclass))
        if not self._class_atom:
            fehler = C.get_last_error()
            if fehler != 1410:      # 1410 = Klasse schon vorhanden – unkritisch
                raise OSError(f'Fensterklasse konnte nicht angelegt werden (Fehler {fehler}).')
        self.hwnd = u.CreateWindowExW(0, klasse, 'ChurchTools Bridge', 0, 0, 0, 0, 0,
                                      None, None, self.hinstance, None)
        if not self.hwnd:
            raise OSError(f'Fenster konnte nicht angelegt werden (Fehler {C.get_last_error()}).')
        TrayIcon._windows[self.hwnd] = self
        self._set_proc()
        u.SetWindowLongPtrW.restype = C.c_void_p
        try:
            u.SetWindowLongPtrW.argtypes = [W.HWND, C.c_int, C.c_void_p]
            u.SetWindowLongPtrW(self.hwnd, -21, None)   # GWLP_USERDATA
        except AttributeError:
            pass

    def _set_proc(self):
        """Teilt Windows die Fensterprozedur mit."""
        u = self.user32
        if hasattr(u, 'SetWindowLongPtrW'):
            u.SetWindowLongPtrW(self.hwnd, -4,           # GWLP_WNDPROC
                                C.cast(self._handler, C.c_void_p))
        else:
            u.SetWindowLongW(self.hwnd, -4,
                             C.cast(self._handler, C.c_void_p))

    def _load_icons(self):
        for name, datei in (('online', 'tray-online.ico'), ('offline', 'tray-offline.ico')):
            pfad = assets_dir() / datei
            if not pfad.exists():
                raise OSError(f'Icon fehlt: {pfad}')
            handle = load_icon(pfad)
            if not handle:
                raise OSError(f'Icon konnte nicht geladen werden: {pfad}')
            self._icons[name] = handle

    def _icon_for(self):
        name = 'online' if self.online else 'offline'
        return self._icons.get(name) or self._icons.get('offline')

    def _fill(self):
        daten = NOTIFYICONDATAW()
        daten.cbSize = C.sizeof(NOTIFYICONDATAW)
        daten.hWnd = self.hwnd
        daten.uID = self.uid
        daten.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
        daten.uCallbackMessage = 0x0400 + 1        # WM_APP + 1
        daten.hIcon = self._icon_for()
        daten.szTip = self.tooltip
        return daten

    def _add_icon(self):
        daten = self._fill()
        for _ in range(3):
            if self.shell32.Shell_NotifyIconW(NIM_ADD, C.byref(daten)):
                self.added = True
                return
        if not self.added:
            raise OSError('Das Symbol konnte nicht in den Infobereich gesetzt werden.')

    def set_online(self, online, tooltip=None):
        """Schaltet die Farbe um und aktualisiert den Hinweistext.

        Der Aufruf nach außen geht nur raus, wenn sich wirklich etwas ändert.
        Sonst erzeugt die Oberfläche im 100-ms-Takt rund 10 Aufrufe je Sekunde
        (gemessene ~21,6 µs je Aufruf, 36 000 Explorer-Aufrufe je Stunde),
        obwohl der Zustand nahezu immer gleich bleibt.
        """
        online = bool(online)
        if tooltip:
            neuer_text = tooltip[:127]
        elif online != self.online:
            neuer_text = 'Bridge läuft' if online else 'Bridge gestoppt'
        else:
            neuer_text = self.tooltip
        geaendert = (online != self.online) or (neuer_text != self.tooltip)
        self.online = online
        self.tooltip = neuer_text
        if not self.added or not geaendert:
            return
        daten = self._fill()
        daten.uFlags |= NIF_TIP
        self.shell32.Shell_NotifyIconW(NIM_MODIFY, C.byref(daten))

    def notify(self, title, text):
        """Kurze Windows-Meldung – hilfreich beim ersten Start."""
        if not self.added:
            return
        daten = self._fill()
        daten.uFlags |= NIF_INFO
        daten.szInfoTitle = title[:63]
        daten.szInfo = text[:255]
        daten.dwInfoFlags = NIIF_INFO
        self.shell32.Shell_NotifyIconW(NIM_MODIFY, C.byref(daten))

    # ------------------------------------------------------------- Nachrichten

    def _wndproc(self, hwnd, msg, wparam, lparam):
        try:
            # Symbol nach einem Neustart der Taskleiste neu anmelden.
            if self._taskbar_created and msg == self._taskbar_created:
                self.added = False
                try:
                    self._add_icon()
                    self.set_online(self.online)
                except OSError:
                    pass
                return 0
            # Eine zweite Bridge bittet: Fenster zeigen bzw. beenden.
            if self._quit_message and msg == self._quit_message:
                self._call(self.on_quit)
                return 0
            if self._show_message and msg == self._show_message:
                self._call(self.on_open)
                return 0
            if msg == 0x0400 + 1:                      # Symboleingabe
                if lparam in (WM_LBUTTONUP, WM_LBUTTONDBLCLK):
                    self._call(self.on_open)
                elif lparam == WM_RBUTTONUP:
                    self._menu()
                return 0
        except Exception:
            pass
        return self.user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def _call(self, funktion):
        if funktion:
            try:
                funktion()
            except Exception:
                pass

    def _menu(self):
        """Zeigt das Menü an der Mausposition."""
        u = self.user32
        menu = u.CreatePopupMenu()
        status = 'Bridge läuft' if self.online else 'Bridge gestoppt'
        u.AppendMenuW(menu, MF_STRING | MF_GRAYED, self.STATUS, status)
        u.AppendMenuW(menu, MF_SEPARATOR, 0, None)
        u.AppendMenuW(menu, MF_STRING, self.OPEN, 'Fenster öffnen')
        u.AppendMenuW(menu, MF_SEPARATOR, 0, None)
        u.AppendMenuW(menu, MF_STRING, self.QUIT, 'Beenden')
        punkt = W.POINT()
        u.GetCursorPos(C.byref(punkt))
        u.SetForegroundWindow(self.hwnd)
        u.TrackPopupMenu.restype = W.BOOL
        u.TrackPopupMenu.argtypes = [W.HMENU, W.UINT, C.c_int, C.c_int,
                                     C.c_int, W.HWND, C.c_void_p]
        wahl = u.TrackPopupMenu(menu, TPM_RIGHTBUTTON | TPM_RETURNCMD,
                                punkt.x, punkt.y, 0, self.hwnd, None)
        u.PostMessageW(self.hwnd, WM_NULL, 0, 0)
        u.DestroyMenu(menu)
        if wahl == self.OPEN:
            self._call(self.on_open)
        elif wahl == self.QUIT:
            self._call(self.on_quit)

    def pump(self):
        """Verarbeitet die Windows-Nachrichten dieses Fensters. Regelmäßig rufen."""
        if not self.hwnd:
            return
        nachricht = W.MSG()
        u = self.user32
        user32_peek = getattr(u, 'PeekMessageW')
        user32_peek.argtypes = [C.POINTER(W.MSG), W.HWND, W.UINT, W.UINT, W.UINT]
        while user32_peek(C.byref(nachricht), self.hwnd, 0, 0, 1):   # PM_REMOVE
            u.TranslateMessage(C.byref(nachricht))
            u.DispatchMessageW(C.byref(nachricht))

    def close(self):
        """Entfernt das Symbol und gibt die Ressourcen frei."""
        if self.hwnd and self.added:
            daten = self._fill()
            self.shell32.Shell_NotifyIconW(NIM_DELETE, C.byref(daten))
            self.added = False
        TrayIcon._windows.pop(self.hwnd, None)
        if self.hwnd:
            self.user32.DestroyWindow(self.hwnd)
            self.hwnd = None
        # Icons freigeben – LoadImageW zählt sie sonst bis zum Programmende hoch.
        for handle in self._icons.values():
            if handle:
                self.user32.DestroyIcon(handle)
        self._icons.clear()