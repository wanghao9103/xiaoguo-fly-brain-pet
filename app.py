"""Xiao Guo: an offline Windows desktop pet with a sparse online action network."""
import argparse
import ctypes
from ctypes import wintypes
from datetime import datetime
import json
import logging
import math
import os
from pathlib import Path
import random
import queue
import sys
import time
import webbrowser
import tkinter as tk
from tkinter import messagebox, ttk

from brain import ACTIONS, ACTION_LABELS
from engine import PetEngine, bounded
from interaction import InteractionState
from mood import MOODS, ambient_message, select_mood, tear_phases
from storage import InstanceLock, PetStore

ROOT = Path(__file__).resolve().parent
WIDTH, HEIGHT = 208, 208
DISPLAY_SIZES = {"mini": 156, "small": 208, "medium": 280}
KEY = "#ff00ff"
INK, GREEN, PAPER = "#173f35", "#278366", "#f4f7f2"
QUICK_ACTIONS = (("pet", "摸"), ("feed", "喂"), ("play", "玩"), ("praise", "赞"), ("menu", "⋯"))


def enable_dpi():
    if os.name == "nt":
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except (AttributeError, OSError):
            pass


def work_area(root):
    if os.name == "nt":
        rect = wintypes.RECT()
        if ctypes.windll.user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(rect), 0):
            return rect.left, rect.top, rect.right, rect.bottom
    return 0, 0, root.winfo_screenwidth(), root.winfo_screenheight()


def clamp_position(x, y, area, size=(WIDTH, HEIGHT)):
    left, top, right, bottom = area
    return (max(left, min(max(left, right - size[0]), x)),
            max(top, min(max(top, bottom - size[1]), y)))


class DesktopPet:
    def __init__(self, engine, store, show_panel=False):
        self.engine, self.store = engine, store
        self.root = tk.Tk()
        self.size_name = "small"
        display_path = self.store.directory / "display.json"
        if display_path.exists():
            try:
                display = json.loads(display_path.read_text(encoding="utf-8"))
                if isinstance(display, dict) and display.get("size") in DISPLAY_SIZES:
                    self.size_name = display["size"]
            except (OSError, ValueError, TypeError):
                logging.warning("Invalid display preferences; using small size")
        # Character size is an explicit user preference, independent of OS text scaling.
        self.render_scale = DISPLAY_SIZES[self.size_name] / WIDTH
        self.width, self.height = round(WIDTH * self.render_scale), round(HEIGHT * self.render_scale)
        self.root.title("小果 · 果蝇神经网络桌面宠物")
        self.root.configure(bg=KEY)
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        if os.name == "nt":
            self.root.attributes("-transparentcolor", KEY)
            self.root.attributes("-toolwindow", True)
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.bind("<Escape>", lambda event: self.close())
        self.root.report_callback_exception = self.callback_error
        self.canvas = tk.Canvas(self.root, width=self.width, height=self.height, bg=KEY,
                                highlightthickness=0, cursor="hand2")
        self.canvas.pack()
        self.canvas.bind("<ButtonPress-1>", self.press)
        self.canvas.bind("<B1-Motion>", self.drag)
        self.canvas.bind("<ButtonRelease-1>", self.release)
        self.canvas.bind("<Double-Button-1>", self.double_click)
        self.canvas.bind("<Button-3>", self.open_menu)
        self.area = work_area(self.root)
        initial = engine.position or [self.area[2] - self.width - 50, self.area[3] - self.height - 35]
        self.x, self.y = self.clamp(*initial)
        self.root.geometry(f"{self.width}x{self.height}{int(self.x):+d}{int(self.y):+d}")
        self.rng = random.Random(9)  # visual movement RNG does not consume the brain's RNG
        self.target = (self.x, self.y)
        self.last_tick = time.monotonic()
        self.elapsed = 0.0
        self.last_save = self.last_tick
        self.last_panel = 0.0
        self.feedback_until = 0.0
        self.feedback_message = ""
        self.interaction = InteractionState()
        self.hovered = False
        self.greeting_until = self.last_tick + 6
        self.press_target = None
        self.double_release = False
        self.click_delay = int(ctypes.windll.user32.GetDoubleClickTime()) + 30 if os.name == "nt" else 530
        self.dragging = False
        self.moved = False
        self.press_anchor = None
        self.single_click = None
        self.single_context = None
        self.previous_pointer = None
        self.cursor_speed = 0.0
        self.closing = False
        self.panel = None
        self.lab_service = None
        self.board_events = queue.SimpleQueue()
        self.save_status = "本地记忆已就绪"
        self.dirty_error = False
        self.menu = tk.Menu(self.root, tearoff=False, font=("Microsoft YaHei UI", 10))
        for label, kind in (("摸摸小果", "pet"), ("喂一颗果糖", "feed"),
                            ("喜欢这个动作", "praise"), ("不要这样", "discourage")):
            self.menu.add_command(label=label, command=lambda event=kind: self.interact(event))
        self.menu.add_command(label="逗小果玩：追鼠标", command=self.start_game)
        self.menu.add_separator()
        self.menu.add_command(label="状态与学习面板", command=self.show_panel)
        self.menu.add_command(label="看看它这次的选择", command=self.explain_decision)
        self.menu.add_command(label="神经网络实验室（独立副本）", command=self.open_lab)
        self.menu.add_command(label="和小果下棋：五子棋 / 象棋", command=self.open_chess)
        self.menu.add_command(label="暂停 / 继续", command=lambda: self.toggle("paused"))
        self.menu.add_command(label="原地陪伴 / 自由活动", command=lambda: self.toggle("stay"))
        self.size_var = tk.StringVar(value=self.size_name)
        size_menu = tk.Menu(self.menu, tearoff=False, font=("Microsoft YaHei UI", 10))
        for name, label in (("mini", "迷你"), ("small", "小号"), ("medium", "中号")):
            size_menu.add_radiobutton(label=label, value=name, variable=self.size_var,
                                     command=lambda value=name: self.set_size(value))
        self.menu.add_cascade(label="宠物大小", menu=size_menu)
        self.menu.add_separator()
        self.menu.add_command(label="保存并退出", command=self.close)
        self.engine.start_session()
        self.engine.decide(self.observe(.1))
        self.choose_target()
        self.draw()
        self.root.after(42, self.tick)
        if show_panel:
            self.root.after(200, self.show_panel)
        self.save()

    def callback_error(self, exc, value, traceback):
        logging.error("Desktop callback error", exc_info=(exc, value, traceback))
        self.engine.settings["paused"] = True
        if not self.dirty_error:
            self.dirty_error = True
            messagebox.showerror("小果暂停了", "发生了界面错误，活动已暂停。详情记录在本地 app.log。", parent=self.root)

    def clamp(self, x, y):
        return clamp_position(x, y, self.area, (self.width, self.height))

    def set_size(self, name):
        if name not in DISPLAY_SIZES:
            raise ValueError("Unknown pet size.")
        old_width, old_height = self.width, self.height
        self.size_name = name
        self.size_var.set(name)
        self.render_scale = DISPLAY_SIZES[name] / WIDTH
        self.width = self.height = DISPLAY_SIZES[name]
        self.x, self.y = self.clamp(self.x + (old_width - self.width) / 2,
                                    self.y + old_height - self.height)
        self.target = (self.x, self.y)
        self.canvas.configure(width=self.width, height=self.height)
        self.root.geometry(f"{self.width}x{self.height}{int(self.x):+d}{int(self.y):+d}")
        try:
            PetStore.atomic_write(self.store.directory / "display.json", json.dumps({"size": name}))
        except OSError:
            logging.exception("Could not save display size")
        self.save()
        self.draw()

    def observe(self, dt):
        pointer = self.root.winfo_pointerxy()
        if self.previous_pointer is not None:
            raw_speed = math.dist(pointer, self.previous_pointer) / max(.016, dt)
            self.cursor_speed = .75 * self.cursor_speed + .25 * raw_speed
        self.previous_pointer = pointer
        distance = math.dist(pointer, (self.x + self.width / 2, self.y + self.height / 2))
        left, top, right, bottom = self.area
        edge_distance = min(self.x - left, self.y - top, right - self.x - self.width, bottom - self.y - self.height)
        hour = datetime.now().hour + datetime.now().minute / 60
        return {"cursor_near": bounded(1 - distance / 600),
                "cursor_slow": bounded(1 - self.cursor_speed / 1500),
                "edge_near": bounded(1 - edge_distance / 160),
                "daylight": bounded(math.sin((hour - 6) * math.pi / 12))}

    def choose_target(self):
        if self.engine.action == "wander":
            self.target = self.clamp(self.x + self.rng.uniform(-130, 130) * self.render_scale,
                                     self.y + self.rng.uniform(-55, 55) * self.render_scale)
        else:
            self.target = (self.x, self.y)

    def tick(self):
        if self.closing:
            return
        now = time.monotonic()
        for _ in range(8):
            try:
                board_event = self.board_events.get_nowait()
            except queue.Empty:
                break
            self.handle_board_event(board_event)
        dt = min(.2, max(0, now - self.last_tick))
        self.last_tick = now
        self.elapsed += dt
        if int(self.elapsed * 10) % 50 == 0:
            self.area = work_area(self.root)
        observation = self.observe(dt)
        px, py = self.previous_pointer
        self.hovered = self.x <= px < self.x + self.width and self.y <= py < self.y + self.height
        if not self.dragging:
            changed = self.engine.advance(dt, observation, allow_decisions=not self.interaction.playing)
            if changed:
                self.choose_target()
            if not self.engine.settings["paused"] and not self.engine.settings["stay"]:
                if self.interaction.playing:
                    self.target = self.clamp(px - 72 * self.render_scale, py - 112 * self.render_scale)
                elif self.engine.action == "approach":
                    px, py = self.previous_pointer
                    # Stop beside the cursor so the pet does not sit on its click target.
                    self.target = self.clamp(px + 55 * self.render_scale, py - self.height / 2)
                busy = self.interaction.effect in ("pet", "feed", "discourage")
                may_move = self.interaction.playing or not self.hovered
                if may_move and not busy and (self.interaction.playing or self.engine.action in ("wander", "approach")):
                    dx, dy = self.target[0] - self.x, self.target[1] - self.y
                    distance = math.hypot(dx, dy)
                    if distance > 2:
                        mood = select_mood(self.engine.body, playing=self.interaction.playing)
                        speed = 140 if self.interaction.playing else 34 * mood.motion
                        step = min(distance, speed * self.render_scale * dt)
                        self.x += dx / distance * step
                        self.y += dy / distance * step
            self.x, self.y = self.clamp(self.x, self.y)
            self.root.geometry(f"{self.width}x{self.height}{int(self.x):+d}{int(self.y):+d}")
        distance = math.dist(self.previous_pointer, (self.x + 104 * self.render_scale,
                                                     self.y + 112 * self.render_scale)) / self.render_scale
        events = self.interaction.advance(dt, distance, paused=self.engine.settings["paused"] or self.dragging)
        for event in events:
            if event == "catch":
                self.interaction.react("catch", 1.0)
                self.feedback_message = f"接近你啦！{self.interaction.catches}/3"
                self.feedback_until = now + 1.2
            elif event == "finish":
                self.finish_game()
        self.draw()
        if self.panel is not None and now - self.last_panel > .75:
            self.update_panel()
            self.last_panel = now
        if now - self.last_save > 30:
            self.save()
        self.root.after(42, self.tick)

    def draw(self):
        c = self.canvas
        c.delete("all")
        action = self.engine.action
        paused = self.engine.settings["paused"]
        phase = 0 if paused else self.elapsed
        effect = self.interaction.effect
        mood = select_mood(self.engine.body, paused=paused, playing=self.interaction.playing)
        responding = bool(effect or self.hovered or self.dragging or self.interaction.playing)
        quiet_mood = MOODS["calm"] if responding else mood
        bob = math.sin(phase * (6 if action == "play" else 2)) * (7 if action == "play" else 2)
        if quiet_mood.code in ("bored", "sleepy", "tearful"):
            bob = math.sin(phase * .8) * 1.5 + 3
        if effect in ("touch", "pet", "praise", "catch", "drop"):
            bob -= abs(math.sin(self.interaction.progress * math.pi * 3)) * 5
        cy = 117 + bob
        wing_rate = (20 if self.dragging else 15 if action in ("play", "approach") else 5) * quiet_mood.wing
        flap = math.sin(phase * wing_rate) * (8 if responding else 8 * quiet_mood.wing)
        # Wings, six little legs, a rounded mint body and amber head markings.
        c.create_oval(30, cy - 60 - flap, 94, cy - 13, fill="#e9f4ec", outline="#8db5a3", width=2)
        c.create_oval(114, cy - 60 + flap, 178, cy - 13, fill="#e9f4ec", outline="#8db5a3", width=2)
        c.create_line(42, cy - 43 - flap / 2, 92, cy - 20, fill="#c2d9cc", width=2)
        c.create_line(166, cy - 43 + flap / 2, 116, cy - 20, fill="#c2d9cc", width=2)
        stride = math.sin(phase * 9) * (4 if action in ("wander", "play") else 1)
        for i in range(3):
            offset = 13 + i * 12
            c.create_line(80, cy + offset - 10, 57 - i * 2, cy + offset + stride,
                          49 - i * 2, cy + offset - 3 + stride, fill=INK, width=3, smooth=True)
            c.create_line(128, cy + offset - 10, 151 + i * 2, cy + offset - stride,
                          159 + i * 2, cy + offset - 3 - stride, fill=INK, width=3, smooth=True)
        c.create_oval(68, cy - 4, 140, cy + 44, fill="#78b393", outline=INK, width=3)
        c.create_arc(69, cy + 8, 139, cy + 38, start=185, extent=170, style="arc", outline="#539270", width=3)
        c.create_oval(57, cy - 52, 151, cy + 24, fill="#bae5bf", outline=INK, width=3)
        c.create_oval(73, cy - 48, 133, cy - 17, fill="#d6efc8", outline="")
        droop = quiet_mood.droop
        c.create_line(87, cy - 45, 76, cy - 68 + droop, 67, cy - 68 + droop, fill=INK, width=3, smooth=True)
        c.create_line(121, cy - 45, 132, cy - 68 + droop, 141, cy - 68 + droop, fill=INK, width=3, smooth=True)
        c.create_oval(62, cy - 73 + droop, 72, cy - 63 + droop, fill="#edbd63", outline=INK, width=2)
        c.create_oval(136, cy - 73 + droop, 146, cy - 63 + droop, fill="#edbd63", outline=INK, width=2)
        sleeping = action == "rest" and not responding and quiet_mood.code in ("calm", "sleepy", "paused")
        hearts = effect in ("touch", "pet", "praise", "catch")
        happy = hearts or quiet_mood.code == "content"
        yawning = (not paused and not responding and quiet_mood.code == "sleepy" and
                   self.engine.body["age_seconds"] % 18 < 2)
        blink = not paused and int(phase * 10) % 47 in (0, 1)
        for ex in (82, 126):
            if happy:
                c.create_arc(ex - 9, cy - 20, ex + 9, cy - 4, start=5, extent=170,
                             style="arc", outline=INK, width=3)
            elif sleeping or blink:
                c.create_arc(ex - 10, cy - 22, ex + 10, cy - 8, start=185, extent=170,
                             style="arc", outline=INK, width=3)
            elif quiet_mood.code == "tearful":
                c.create_oval(ex - 12, cy - 24, ex + 12, cy + 2, fill="#f3fbff", outline=INK, width=2)
                c.create_oval(ex - 5, cy - 16, ex + 5, cy - 2, fill=INK, outline="")
                c.create_oval(ex - 4, cy - 16, ex, cy - 12, fill="white", outline="")
                c.create_line(ex - 10, cy - 25, ex + 8, cy - 30, fill=INK, width=2)
            elif quiet_mood.code in ("bored", "sleepy"):
                c.create_oval(ex - 12, cy - 14, ex + 12, cy + 2, fill="#fffdf0", outline=INK, width=2)
                c.create_oval(ex - 4, cy - 11, ex + 4, cy - 1, fill=INK, outline="")
                c.create_line(ex - 11, cy - 17, ex + 8, cy - 15, fill=INK, width=2)
            else:
                c.create_oval(ex - 13, cy - 28, ex + 13, cy + 2, fill="#fffdf0", outline=INK, width=2)
                px, py = self.previous_pointer or (self.x + 104, self.y + 110)
                look_x = bounded((px - self.x - self.width / 2) / (150 * self.render_scale), -3, 3)
                look_y = bounded((py - self.y - self.height / 2) / (150 * self.render_scale), -2, 2)
                if quiet_mood.code == "curious":
                    look_x, look_y = math.sin(phase * 1.3) * 4, -1
                c.create_oval(ex - 5 + look_x, cy - 19 + look_y, ex + 5 + look_x, cy - 4 + look_y,
                              fill=INK, outline="")
                c.create_oval(ex - 2 + look_x, cy - 17 + look_y, ex + 2 + look_x, cy - 13 + look_y,
                              fill="white", outline="")
        c.create_oval(63, cy - 1, 78, cy + 6, fill="#eba98f", outline="")
        c.create_oval(130, cy - 1, 145, cy + 6, fill="#eba98f", outline="")
        if self.dragging or effect == "feed" or yawning:
            mouth = 3 + 2 * abs(math.sin(phase * 13))
            c.create_oval(100, cy + 2 - mouth, 110, cy + 4 + mouth, fill=INK, outline="")
        elif quiet_mood.code in ("bored", "tearful"):
            c.create_arc(97, cy + 5, 112, cy + 14, start=5, extent=170, style="arc", outline=INK, width=2)
        else:
            c.create_arc(96, cy - 1, 113, cy + 11, start=185, extent=170, style="arc", outline=INK, width=2)
        if quiet_mood.code == "tearful":
            for tx, progress in zip((75, 133), tear_phases(self.engine.body)):
                ty = cy + progress * 24
                c.create_polygon(tx, ty - 5, tx - 4, ty + 2, tx - 2, ty + 6,
                                 tx + 2, ty + 6, tx + 4, ty + 2, smooth=True,
                                 fill="#84cbea", outline="#5aa7ce", width=1, tags="tear")
        if hearts:
            for hx, hy in ((44, 88), (162, 63)):
                hy -= 9 * self.interaction.progress
                c.create_oval(hx - 6, hy - 4, hx, hy + 2, fill="#df7e87", outline="")
                c.create_oval(hx, hy - 4, hx + 6, hy + 2, fill="#df7e87", outline="")
                c.create_polygon(hx - 6, hy, hx + 6, hy, hx, hy + 8, fill="#df7e87", outline="")
        if effect == "feed":
            t = self.interaction.progress
            fruit_x = 170 - 56 * min(1, t * 1.6)
            fruit_y = 146 - 23 * min(1, t * 1.6)
            radius = 10 * max(.15, 1 - max(0, t - .55) * 2)
            c.create_oval(fruit_x - radius, fruit_y - radius, fruit_x + radius, fruit_y + radius,
                          fill="#efb658", outline="#98682c", width=1)
            c.create_polygon(fruit_x, fruit_y - radius, fruit_x + 7, fruit_y - radius - 8,
                             fruit_x + 9, fruit_y - radius - 1, fill=GREEN, outline="")
        if self.interaction.playing:
            for dot in range(3):
                c.create_oval(85 + dot * 14, 164, 93 + dot * 14, 172,
                              fill="#e8b755" if dot < self.interaction.catches else "#fffdf3", outline="#bbbd9c")
        if sleeping:
            c.create_text(167, 75, text="z", fill="#658574", font=("Segoe UI", -round(16 * self.render_scale), "bold"))
        now = time.monotonic()
        message = self.feedback_message if now < self.feedback_until else ""
        if not message and self.interaction.playing:
            message = f"移动鼠标逗我 · {math.ceil(self.interaction.game_left)}秒"
        if not message and self.hovered:
            message = self.engine.describe_decision(compact=True)
        if not message and now < self.greeting_until:
            message = "你好，点下面和我玩"
        if not message and not responding:
            message = ambient_message(mood, self.engine.body["idle"])
        if self.dragging and self.moved:
            message = "飞起来啦～轻轻放下我"
        if paused:
            message = "暂停中 · 右键继续"
        if message:
            c.create_rectangle(14, 8, 194, 37, fill="#fffdf3", outline="#c4d7bc", width=1)
            c.create_polygon(97, 37, 104, 45, 112, 37, fill="#fffdf3", outline="")
            c.create_text(104, 22, text=message, fill=INK, font=("Microsoft YaHei UI", -round(11 * self.render_scale)))
        for index, (kind, label) in enumerate(QUICK_ACTIONS):
            if kind == "play" and self.interaction.playing:
                label = "停"
            x = 17 + 36 * index
            c.create_oval(x, 177, x + 30, 203, fill="#fffdf3", outline="#aac7aa")
            c.create_text(x + 15, 190, text=label, fill=INK,
                          font=("Microsoft YaHei UI", -round(12 * self.render_scale), "bold"))
        c.scale("all", 0, 0, self.render_scale, self.render_scale)

    def press(self, event):
        self.press_target = self.quick_action_at(event.x, event.y) if hasattr(event, "x") else None
        if self.press_target is not None:
            self.cancel_single_click()
        else:
            self.interaction.react("touch", self.click_delay / 1000 + .2)
        self.dragging = True
        self.moved = False
        self.press_anchor = (event.x_root, event.y_root, self.x, self.y)

    def drag(self, event):
        if self.press_anchor is None:
            return
        sx, sy, x, y = self.press_anchor
        dx, dy = event.x_root - sx, event.y_root - sy
        if abs(dx) + abs(dy) > 5:
            if not self.moved:
                self.cancel_single_click()
                if self.interaction.playing:
                    self.finish_game(cancelled=True)
            self.moved = True
        if self.moved:
            self.x, self.y = self.clamp(x + dx, y + dy)
            self.root.geometry(f"{self.width}x{self.height}{int(self.x):+d}{int(self.y):+d}")
            self.target = (self.x, self.y)

    def release(self, event):
        self.dragging = False
        self.press_anchor = None
        if self.double_release:
            self.double_release = False
            self.press_target = None
            return
        if self.moved:
            self.interaction.react("drop", .9)
            self.feedback_message = "在这里继续陪你"
            self.feedback_until = time.monotonic() + 2
            self.save()
            return
        target = self.quick_action_at(event.x, event.y)
        pressed, self.press_target = self.press_target, None
        if target is not None or pressed is not None:
            if target != pressed:
                return
            self.cancel_single_click()
            if target == "menu":
                self.open_menu(event)
            elif target == "play":
                self.start_game()
            else:
                self.interact(target)
            return
        self.cancel_single_click()
        self.single_context = self.engine.capture_feedback_context()
        self.single_click = self.root.after(self.click_delay, self.commit_single_click)

    def commit_single_click(self):
        context = self.single_context
        self.single_click = None
        self.single_context = None
        if context is not None:
            self.interact("pet", context=context)

    def quick_action_at(self, x, y):
        x, y = x / self.render_scale, y / self.render_scale
        if 177 <= y <= 203:
            for index, (kind, _) in enumerate(QUICK_ACTIONS):
                if 17 + 36 * index <= x <= 47 + 36 * index:
                    return kind
        return None

    def cancel_single_click(self):
        if self.single_click is not None:
            self.root.after_cancel(self.single_click)
            self.single_click = None
        self.single_context = None

    def double_click(self, event):
        self.cancel_single_click()
        self.dragging = False
        self.press_anchor = None
        self.double_release = True
        target = self.quick_action_at(event.x, event.y)
        if target is None:
            self.start_game()
        # A toolbar double-click is one deliberate command, never an extra body pet.

    def open_menu(self, event):
        self.cancel_single_click()
        try:
            self.menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.menu.grab_release()

    def interact(self, kind, context=None):
        self.cancel_single_click()
        self.engine.interact(kind, context=context)
        self.interaction.react(kind, 3.0 if kind == "feed" else 2.5)
        self.feedback_message = self.engine.message
        self.feedback_until = time.monotonic() + 4
        self.save()
        self.update_panel()
        self.draw()

    def start_game(self):
        self.cancel_single_click()
        if self.interaction.playing:
            self.finish_game(cancelled=True)
            return
        if not self.engine.begin_game():
            self.feedback_message = "先继续活动，或让我歇一会儿"
            self.feedback_until = time.monotonic() + 3
            return
        self.interaction.start_game()
        self.feedback_message = "移近再移远，让我追上你"
        self.feedback_until = time.monotonic() + 2
        self.target = (self.x, self.y)
        self.save()
        self.update_panel()
        self.draw()

    def explain_decision(self):
        self.cancel_single_click()
        self.feedback_message = self.engine.describe_decision(compact=True)
        self.feedback_until = time.monotonic() + 4
        self.draw()

    def finish_game(self, cancelled=False):
        catches = self.interaction.catches
        self.interaction.cancel_game()
        self.engine.finish_game(catches, cancelled=cancelled)
        self.interaction.react("praise" if catches and not cancelled else "drop", 2.0)
        self.feedback_message = "先休息一下吧" if cancelled else f"玩完啦！这次接近你 {catches}/3 次"
        self.feedback_until = time.monotonic() + 4
        self.target = (self.x, self.y)
        self.save()
        self.update_panel()

    def cancel_game_for_pause(self):
        if self.interaction.playing:
            self.finish_game(cancelled=True)

    def toggle(self, setting):
        self.engine.settings[setting] = not self.engine.settings[setting]
        if setting == "paused":
            self.cancel_single_click()
            if self.engine.settings[setting]:
                self.cancel_game_for_pause()
            # No reward may leak across an explicit pause/resume boundary.
            self.engine.pending_features = None
            self.engine.decision_elapsed = 0.0
            self.last_tick = time.monotonic()
        self.save()
        self.update_panel()

    def set_option(self, setting, variable):
        self.engine.settings[setting] = bool(variable.get())
        if setting == "paused":
            self.cancel_single_click()
            if self.engine.settings[setting]:
                self.cancel_game_for_pause()
            self.engine.pending_features = None
            self.engine.decision_elapsed = 0.0
        self.save()
        self.update_panel()

    def show_panel(self):
        if self.panel is not None:
            self.panel.deiconify()
            self.panel.lift()
            return
        self.panel = tk.Toplevel(self.root)
        self.panel.title("小果 · 状态与学习")
        self.panel.configure(bg=PAPER)
        self.panel.geometry("530x720")
        self.panel.minsize(510, 680)
        self.panel.protocol("WM_DELETE_WINDOW", self.hide_panel)
        self.panel.bind("<Escape>", lambda event: self.hide_panel())
        style = ttk.Style(self.panel)
        style.configure("Pet.Horizontal.TProgressbar", troughcolor="#e1e9df", background=GREEN)
        viewport = tk.Canvas(self.panel, bg=PAPER, highlightthickness=0, width=530, height=720)
        scrollbar = ttk.Scrollbar(self.panel, orient="vertical", command=viewport.yview)
        scrollbar.pack(side="right", fill="y")
        viewport.pack(side="left", fill="both", expand=True)
        viewport.configure(yscrollcommand=scrollbar.set)
        outer = tk.Frame(viewport, bg=PAPER, padx=24, pady=18)
        content = viewport.create_window(0, 0, window=outer, anchor="nw")
        outer.bind("<Configure>", lambda event: viewport.configure(scrollregion=viewport.bbox("all")))
        viewport.bind("<Configure>", lambda event: viewport.itemconfigure(content, width=event.width))
        self.panel_viewport, self.panel_content = viewport, outer
        self.panel.bind("<MouseWheel>", lambda event: viewport.yview_scroll(-int(event.delta / 120), "units"))
        tk.Label(outer, text="小果的日常", bg=PAPER, fg=INK,
                 font=("Microsoft YaHei UI", 21, "bold")).pack(anchor="w")
        tk.Label(outer, text="会从反馈里学习的离线小伙伴", bg=PAPER, fg="#617b70",
                 font=("Microsoft YaHei UI", 10)).pack(anchor="w", pady=(1, 12))
        self.status_var = tk.StringVar()
        tk.Label(outer, textvariable=self.status_var, bg="#e4eee2", fg=INK,
                 padx=12, pady=9, anchor="w", font=("Microsoft YaHei UI", 11)).pack(fill="x")
        self.decision_var = tk.StringVar()
        tk.Label(outer, textvariable=self.decision_var, bg=PAPER, fg="#617b70",
                 font=("Microsoft YaHei UI", 9), anchor="w").pack(fill="x", pady=(5, 0))
        stats = tk.Frame(outer, bg=PAPER)
        stats.pack(fill="x", pady=12)
        self.body_vars = {}
        for row, (key, label) in enumerate((("energy", "精力"), ("satiety", "饱食"),
                                           ("social", "互动满足"), ("curiosity", "探索倾向"))):
            tk.Label(stats, text=label, bg=PAPER, fg=INK, width=9, anchor="w",
                     font=("Microsoft YaHei UI", 10)).grid(row=row, column=0, sticky="w", pady=3)
            variable = tk.DoubleVar()
            ttk.Progressbar(stats, variable=variable, maximum=1, style="Pet.Horizontal.TProgressbar").grid(
                row=row, column=1, sticky="ew", padx=8)
            percent = tk.StringVar()
            tk.Label(stats, textvariable=percent, bg=PAPER, fg="#617b70", width=5,
                     font=("Segoe UI", 10)).grid(row=row, column=2)
            self.body_vars[key] = (variable, percent)
        stats.columnconfigure(1, weight=1)
        buttons = tk.Frame(outer, bg=PAPER)
        buttons.pack(fill="x", pady=(0, 12))
        for col, (text, kind) in enumerate((("摸摸", "pet"), ("喂食", "feed"),
                                          ("鼓励当前动作", "praise"), ("制止当前动作", "discourage"))):
            tk.Button(buttons, text=text, command=lambda k=kind: self.interact(k),
                      bg="white", fg=INK, relief="flat", padx=8, pady=7,
                      font=("Microsoft YaHei UI", 9)).grid(row=0, column=col, padx=(0, 6), sticky="ew")
            buttons.columnconfigure(col, weight=1)
        tk.Label(outer, text="此刻的行动倾向", bg=PAPER, fg=INK,
                 font=("Microsoft YaHei UI", 11, "bold")).pack(anchor="w")
        self.probability_var = tk.StringVar()
        tk.Label(outer, textvariable=self.probability_var, bg=PAPER, fg="#526f62",
                 justify="left", font=("Microsoft YaHei UI", 10)).pack(anchor="w", pady=(4, 6))
        self.neurons = tk.Canvas(outer, bg="#e4ebe2", height=63, highlightthickness=0)
        self.neurons.pack(fill="x")
        self.learning_var = tk.StringVar()
        tk.Label(outer, textvariable=self.learning_var, bg=PAPER, fg="#526f62",
                 font=("Microsoft YaHei UI", 9)).pack(anchor="w", pady=(5, 9))
        options = tk.Frame(outer, bg=PAPER)
        options.pack(fill="x", pady=(0, 10))
        self.option_vars = {}
        for setting, text in (("paused", "暂停活动"), ("frozen", "冻结学习"), ("stay", "原地陪伴")):
            var = tk.BooleanVar(value=self.engine.settings[setting])
            self.option_vars[setting] = var
            tk.Checkbutton(options, text=text, variable=var, bg=PAPER, fg=INK,
                           activebackground=PAPER, font=("Microsoft YaHei UI", 9),
                           command=lambda s=setting, v=var: self.set_option(s, v)).pack(side="left", padx=(0, 15))
        tk.Label(outer, text="最近的互动记忆", bg=PAPER, fg=INK,
                 font=("Microsoft YaHei UI", 11, "bold")).pack(anchor="w")
        self.memories = tk.Listbox(outer, height=5, bg="white", fg="#385b4b", relief="flat",
                                  highlightthickness=1, highlightbackground="#d6e0d1",
                                  font=("Microsoft YaHei UI", 9), activestyle="none")
        self.memories.pack(fill="both", expand=True, pady=(6, 10))
        self.save_var = tk.StringVar()
        tk.Label(outer, textvariable=self.save_var, bg=PAPER, fg="#617b70",
                 font=("Microsoft YaHei UI", 9), anchor="w").pack(fill="x")
        tk.Label(outer, text="绿色格子是真实激活单元；状态值是模拟变量。\n行为学习不等于主观意识。关闭面板后，小果仍留在桌面。",
                 bg=PAPER, fg="#7b8c80", justify="left",
                 font=("Microsoft YaHei UI", 8)).pack(anchor="w", pady=(8, 10))
        footer = tk.Frame(outer, bg=PAPER)
        footer.pack(fill="x")
        tk.Button(footer, text="回到桌面", command=self.hide_panel, bg=GREEN, fg="white",
                  relief="flat", padx=18, pady=8, font=("Microsoft YaHei UI", 10)).pack(side="left")
        tk.Button(footer, text="保存并退出", command=self.close, bg="white", fg=INK,
                  relief="flat", padx=15, pady=8, font=("Microsoft YaHei UI", 10)).pack(side="right")
        self.update_panel()
        self.panel.update_idletasks()
        available_w = self.area[2] - self.area[0] - 40
        available_h = self.area[3] - self.area[1] - 80
        panel_w = min(available_w, max(530, outer.winfo_reqwidth() + scrollbar.winfo_reqwidth()))
        panel_h = min(available_h, max(720, outer.winfo_reqheight()))
        self.panel.geometry(f"{panel_w}x{panel_h}+{self.area[0] + 20}+{self.area[1] + 30}")
        self.panel.minsize(min(530, available_w), min(600, available_h))

    def open_lab(self):
        self.cancel_single_click()
        try:
            if self.lab_service is None:
                from lab import LabService
                self.lab_service = LabService(initial=self.engine.brain.to_dict(), on_game_event=self.board_events.put).start()
            webbrowser.open(self.lab_service.url)
        except Exception:
            logging.exception("Could not open learning laboratory")
            messagebox.showerror("实验室暂未打开", "实验室启动失败，小果的学习和记忆没有改动。可查看 app.log。", parent=self.root)

    def open_chess(self):
        self.cancel_single_click()
        try:
            if self.lab_service is None:
                from lab import LabService
                self.lab_service = LabService(initial=self.engine.brain.to_dict(), on_game_event=self.board_events.put).start()
            webbrowser.open(self.lab_service.url + "games")
        except Exception:
            logging.exception("Could not open chess table")
            messagebox.showerror("棋桌暂未打开", "棋桌启动失败，原有记忆没有改动。", parent=self.root)

    def handle_board_event(self, event):
        self.feedback_message = event["message"]
        self.feedback_until = time.monotonic() + 4
        self.interaction.react("praise" if event["kind"] == "finish" else "play", 2.0)
        if event["kind"] in ("start", "human_move"):
            self.engine.body["idle"] = 0.0
        if event["kind"] in ("start", "finish"):
            self.engine.remember("board_game", event["message"])
            self.save()

    def update_panel(self):
        if self.panel is None:
            return
        engine = self.engine
        current = ("已暂停" if engine.settings["paused"] else "追鼠标小游戏" if self.interaction.playing
                   else "正在" + ACTION_LABELS[engine.action])
        mood = select_mood(engine.body, paused=engine.settings["paused"], playing=self.interaction.playing)
        self.status_var.set(f"{current} · {mood.label} · 第 {engine.sessions} 次见面")
        self.decision_var.set(engine.describe_decision())
        for key, (variable, label) in self.body_vars.items():
            variable.set(engine.body[key])
            label.set(f"{engine.body[key]:.0%}")
        features = engine.features()
        probabilities = engine.brain.probabilities(features)
        self.probability_var.set("    ".join(f"{ACTION_LABELS[a]} {p:.0%}" for a, p in zip(ACTIONS, probabilities)))
        encoded = engine.brain.encode(features)
        active = [i for i, v in enumerate(encoded) if v > 0]
        self.neurons.delete("all")
        columns, rows = 48, math.ceil(engine.brain.width / 48)
        width = max(450, self.neurons.winfo_width())
        for i in range(engine.brain.width):
            x, y = i % columns * width / columns, i // columns * 63 / rows
            self.neurons.create_rectangle(x + 1, y + 1, x + width / columns - 1, y + 63 / rows - 1,
                                          fill=GREEN if i in active else "#d9e3d6", outline="")
        suffix = "（冻结）" if engine.settings["frozen"] else ""
        self.learning_var.set(f"{len(active)}/{engine.brain.width} 激活 · 权重更新 {engine.brain.updates} 次"
                              f" · 互动反馈 {engine.brain.user_updates} 次 {suffix}")
        for key, variable in self.option_vars.items():
            variable.set(engine.settings[key])
        current_items = tuple(self.memories.get(0, "end"))
        items = tuple(f"{datetime.fromisoformat(item['at']).astimezone().strftime('%H:%M:%S')}  {item['text']}"
                      for item in reversed(engine.memory[-30:]))
        if items != current_items:
            self.memories.delete(0, "end")
            for item in items:
                self.memories.insert("end", item)
        self.save_var.set(self.save_status)

    def hide_panel(self):
        if self.panel is not None:
            self.panel.destroy()
            self.panel = None

    def save(self):
        self.engine.position = [round(self.x), round(self.y)]
        try:
            self.store.save(self.engine)
            self.save_status = "记忆已保存 · " + datetime.now().strftime("%H:%M:%S")
        except (OSError, ValueError) as error:
            logging.exception("Save failed")
            self.save_status = "保存失败，内存中的学习仍保留：" + type(error).__name__
        self.last_save = time.monotonic()

    def close(self):
        if self.closing:
            return
        self.cancel_single_click()
        if self.interaction.playing:
            self.finish_game(cancelled=True)
        self.save()
        if self.save_status.startswith("保存失败"):
            if not messagebox.askyesno("本次记忆尚未保存", "保存失败，仍要退出吗？", parent=self.root):
                return
        self.closing = True
        if self.lab_service is not None:
            self.lab_service.stop()
        self.root.destroy()

    def run(self):
        self.root.mainloop()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path,
                        default=Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "FlyBrainPet")
    parser.add_argument("--panel", action="store_true", help="Open the status and learning panel")
    args = parser.parse_args()
    enable_dpi()
    args.data_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(filename=args.data_dir / "app.log", encoding="utf-8",
                        level=logging.WARNING, format="%(asctime)s %(levelname)s %(message)s")
    lock = InstanceLock(args.data_dir)
    try:
        lock.acquire()
    except RuntimeError as error:
        dialog = tk.Tk()
        dialog.withdraw()
        messagebox.showinfo("小果已经在桌面上", str(error), parent=dialog)
        dialog.destroy()
        return
    try:
        store = PetStore(args.data_dir)
        engine, warning = store.load()
        app = DesktopPet(engine, store, show_panel=args.panel)
        if warning:
            app.root.after(300, lambda: messagebox.showwarning("记忆恢复提示", warning, parent=app.root))
        app.run()
    finally:
        lock.release()


if __name__ == "__main__":
    main()
