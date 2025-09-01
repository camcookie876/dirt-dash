# Camcookie Dirt Dash — single-file Brython game.py
# Built for: minimal HTML (just load Brython), no external audio engines
# Creates: SVG canvas, UI, controls, physics, bots, obstacles, ramps, pause, results, local best time, and sound.
# Notes:
# - Uses WebAudio via Brython's window to synthesize simple tones/engine hum (no Flat.io).
# - All UI is SVG except the name input (created dynamically as HTML, positioned over canvas).
# - Designed to run full-screen and mobile-first; large tap targets; no keyboard required.

from browser import document, html, svg, timer, window
import math, random, time

# ------------------------------------------------------------
# Configuration
# ------------------------------------------------------------
VPW, VPH = 1920, 1080            # SVG viewBox virtual resolution
GROUND_Y = 720                    # Base ground height pivot
TRACK_LEN = 4000                 # Track length in world units
TERRAIN_STEP = 16                # Terrain sample step in px
GRAVITY = 0.6
JUMP_VY = 16.0
MAX_SPEED = 22.0
ACCEL = 0.25
BRAKE = 0.35
FRICTION = 0.01
CAM_EASE = 0.08
BOT_COUNT = 3
COUNTDOWN_MS = 3200
OBSTACLE_SPACING = (280, 520)   # min, max gap
MUTE_DEFAULT = False

# ------------------------------------------------------------
# Helpers
# ------------------------------------------------------------
def clamp(v, lo, hi):
    return hi if v > hi else lo if v < lo else v

def now_ms():
    return int(time.time() * 1000)

def fmt_time_ms(ms):
    s = ms / 1000.0
    return f"{s:0.2f}s"

# Simple seeded RNG for stable terrain/obstacles per session
SESSION_SEED = int(time.time())
random.seed(SESSION_SEED)

# ------------------------------------------------------------
# WebAudio Synth (no external audio)
# ------------------------------------------------------------
class SoundEngine:
    def __init__(self):
        AC = getattr(window, "AudioContext", None) or getattr(window, "webkitAudioContext", None)
        self.ctx = AC.new() if AC else None
        self.unlocked = False
        self.muted = MUTE_DEFAULT
        self.engine_nodes = None
        self.engine_on_flag = False
        self.engine_target_hz = 0.0
        self.engine_hz = 0.0

    def unlock(self, *_):
        if not self.ctx: return
        if self.unlocked: return
        # iOS requires resume on user gesture
        try:
            self.ctx.resume()
        except:
            pass
        self.unlocked = True

    def set_mute(self, flag: bool):
        self.muted = flag
        if flag:
            self.engine_off()

    def click(self):
        if self.muted or not self.ctx or not self.unlocked: return
        self._beep(660, 0.04, 0.02)

    def countdown_beep(self, last=False):
        if self.muted or not self.ctx or not self.unlocked: return
        f = 880 if last else 440
        self._beep(f, 0.12, 0.02)

    def victory(self):
        if self.muted or not self.ctx or not self.unlocked: return
        # Simple arpeggio
        seq = [660, 880, 990, 1320]
        t0 = self.ctx.currentTime
        for i, f in enumerate(seq):
            self._beep(f, 0.12, 0.03, start=t0 + i * 0.13)

    def engine_on(self):
        if self.muted or not self.ctx or not self.unlocked: 
            self.engine_on_flag = False
            return
        if self.engine_nodes: 
            self.engine_on_flag = True
            return
        self.engine_on_flag = True
        o = self.ctx.createOscillator()
        g = self.ctx.createGain()
        lp = self.ctx.createBiquadFilter()
        o.type = "sawtooth"
        o.frequency.value = 0
        g.gain.value = 0.0001
        lp.type = "lowpass"
        lp.frequency.value = 600
        o.connect(lp)
        lp.connect(g)
        g.connect(self.ctx.destination)
        o.start()
        self.engine_nodes = (o, g, lp)

    def engine_off(self):
        self.engine_on_flag = False
        if self.engine_nodes:
            o, g, lp = self.engine_nodes
            try:
                g.gain.linearRampToValueAtTime(0.0001, self.ctx.currentTime + 0.15)
            except:
                g.gain.value = 0.0001
            # Stop later
            def stop_engine():
                try:
                    o.stop()
                except:
                    pass
            timer.set_timeout(stop_engine, 300)
            self.engine_nodes = None

    def engine_set_speed(self, speed):
        # Map speed to engine RPM-ish frequency and gain
        if not self.engine_nodes or not self.engine_on_flag: return
        o, g, lp = self.engine_nodes
        hz = 40 + speed * 12
        hz = clamp(hz, 40, 320)
        self.engine_target_hz = hz
        # smooth follow
        self.engine_hz += (self.engine_target_hz - self.engine_hz) * 0.2
        try:
            o.frequency.setTargetAtTime(self.engine_hz, self.ctx.currentTime, 0.05)
        except:
            o.frequency.value = self.engine_hz
        # Gain follows throttle-ish
        tgt_gain = 0.04 + (speed / MAX_SPEED) * 0.1
        try:
            g.gain.setTargetAtTime(tgt_gain, self.ctx.currentTime, 0.08)
        except:
            g.gain.value = tgt_gain

    def _beep(self, freq, dur, ramp, start=None):
        if not self.ctx: return
        t0 = self.ctx.currentTime if start is None else start
        o = self.ctx.createOscillator()
        g = self.ctx.createGain()
        o.type = "sine"
        o.frequency.value = freq
        g.gain.value = 0.0001
        o.connect(g)
        g.connect(self.ctx.destination)
        o.start(t0)
        try:
            g.gain.linearRampToValueAtTime(0.12, t0 + ramp)
            g.gain.linearRampToValueAtTime(0.0001, t0 + dur)
        except:
            pass
        def stop():
            try:
                o.stop()
            except:
                pass
        timer.set_timeout(stop, int((dur + 0.05) * 1000))


SOUND = SoundEngine()

# ------------------------------------------------------------
# SVG / DOM
# ------------------------------------------------------------
def ensure_svg_root():
    root = document.select_one("#game")
    if root is None:
        root = svg.svg(id="game", width="100%", height="100%", viewBox=f"0 0 {VPW} {VPH}", preserveAspectRatio="xMidYMid slice")
        document <= root
    else:
        root.setAttribute("viewBox", f"0 0 {VPW} {VPH}")
        root.setAttribute("preserveAspectRatio", "xMidYMid slice")
        root.setAttribute("width", "100%")
        root.setAttribute("height", "100%")
    # Disable context menu and selection
    def prevent(e):
        e.preventDefault()
    document.bind("contextmenu", prevent)
    document.select_one("html").style.userSelect = "none"
    document.select_one("body").style.margin = "0"
    document.select_one("body").style.background = "#0b0b0e"
    return root

ROOT = ensure_svg_root()

# Layers
LAYER_BG = svg.g(id="bg")
LAYER_TERRAIN = svg.g(id="terrain")
LAYER_OBS = svg.g(id="obstacles")
LAYER_ACTORS = svg.g(id="actors")
LAYER_HUD = svg.g(id="hud")
LAYER_OVERLAY = svg.g(id="overlay")

for g in [LAYER_BG, LAYER_TERRAIN, LAYER_OBS, LAYER_ACTORS, LAYER_HUD, LAYER_OVERLAY]:
    ROOT <= g

# Simple background gradient
BG_RECT = svg.rect(x=0, y=0, width=VPW, height=VPH, fill="url(#sky)")
defs = svg.defs()
grad = svg.linearGradient(id="sky", x1="0%", y1="0%", x2="0%", y2="100%")
grad <= svg.stop(offset="0%", stop_color="#0e1a2b")
grad <= svg.stop(offset="60%", stop_color="#16253b")
grad <= svg.stop(offset="100%", stop_color="#1d2130")
defs <= grad
ROOT <= defs
LAYER_BG <= BG_RECT

# ------------------------------------------------------------
# Terrain and obstacles
# ------------------------------------------------------------
def terrain_y(x):
    # Smooth combo waves with mild undulation
    return (GROUND_Y 
            + 90 * math.sin((x + 300) / 260.0)
            + 48 * math.sin((x + 800) / 110.0)
            + 24 * math.sin((x - 1200) / 55.0))

def slope_at(x, dx=1.0):
    y1 = terrain_y(x - dx)
    y2 = terrain_y(x + dx)
    return (y2 - y1) / (2*dx)

class Obstacle:
    # types: 'rock', 'log', 'ramp'
    def __init__(self, kind, x):
        self.kind = kind
        self.x = x
        self.y = terrain_y(x)
        self.size = 28 if kind == 'rock' else (40 if kind == 'log' else 80)
        self.node = None

    def render(self, group):
        if self.node:
            self.update_graphics()
            return
        if self.kind == 'rock':
            self.node = svg.circle(r=18, fill="#7d7f86", stroke="#2f3138", stroke_width=3)
        elif self.kind == 'log':
            self.node = svg.rect(width=54, height=20, rx=6, fill="#6b4b2a", stroke="#3e2a17", stroke_width=3)
        else:
            # ramp: triangular wedge
            self.node = svg.polygon(points="", fill="#d1a14f", stroke="#6a4c20", stroke_width=3)
        group <= self.node
        self.update_graphics()

    def update_graphics(self):
        if self.kind in ('rock', 'log'):
            y = self.y
            if self.kind == 'rock':
                self.node.setAttribute("cx", f"{self.x}")
                self.node.setAttribute("cy", f"{y - 20}")
            else:
                self.node.setAttribute("x", f"{self.x - 28}")
                self.node.setAttribute("y", f"{y - 22}")
        else:
            # ramp
            y = self.y
            w = 100
            h = 60
            pts = f"{self.x-10},{y} {self.x+w},{y} {self.x+w},{y-h}"
            self.node.setAttribute("points", pts)

    def collides(self, px, py):
        y = self.y
        if self.kind == 'rock':
            # circle check vs point near ground
            dx = px - self.x
            dy = (py - 20) - (y - 20)
            return (dx*dx + dy*dy) < (24*24)
        elif self.kind == 'log':
            # AABB vs point
            return (self.x - 28 <= px <= self.x + 26) and (y - 22 <= py <= y - 2)
        else:
            # ramp triggers on foot contact region
            return (self.x - 10 <= px <= self.x + 100) and (py >= y - 64 and py <= y)

class ObstacleField:
    def __init__(self, length):
        self.length = length
        self.items = []
        self._generate()

    def _generate(self):
        x = 400
        while x < self.length - 200:
            gap = random.randint(*OBSTACLE_SPACING)
            x += gap
            kind = random.choice(['rock', 'log', 'ramp', 'rock', 'log'])
            self.items.append(Obstacle(kind, x))

    def render(self, group):
        for it in self.items:
            it.render(group)

# ------------------------------------------------------------
# Bike / Actor
# ------------------------------------------------------------
class Bike:
    def __init__(self, name, color="#7fc8ff", is_bot=False):
        self.name = name
        self.color = color
        self.is_bot = is_bot
        self.reset()

        # SVG nodes
        self.group = svg.g()
        self.body = svg.rect(width=60, height=20, rx=8, fill=color, stroke="#1b2a38", stroke_width=3)
        self.wheel_f = svg.circle(r=14, fill="#222831", stroke="#0d1116", stroke_width=2)
        self.wheel_b = svg.circle(r=14, fill="#222831", stroke="#0d1116", stroke_width=2)
        self.label = svg.text(self.name, x=0, y=0, fill="#e6f2ff", font_size="22px", text_anchor="middle")
        self.group <= self.body
        self.group <= self.wheel_f
        self.group <= self.wheel_b
        self.group <= self.label
        LAYER_ACTORS <= self.group

    def reset(self):
        self.x = 40
        self.y = terrain_y(self.x) - 30
        self.vx = 0.0
        self.vy = 0.0
        self.on_ground = True
        self.finished = False
        self.finish_time_ms = None
        # Bot params
        if self.is_bot:
            base = random.uniform(0.60, 0.88)
            self.speed_bias = base
            self.jump_bias = random.uniform(0.55, 0.85)

    def update_physics(self, dt, throttle, brake, want_jump):
        if self.finished:
            return
        # Horizontal control
        if throttle:
            self.vx += ACCEL
        if brake:
            self.vx -= BRAKE
        # Drag
        if not throttle and not brake:
            self.vx *= (1.0 - FRICTION)
        self.vx = clamp(self.vx, 0.0, MAX_SPEED)

        # Vertical / ground follow
        ground = terrain_y(self.x)
        if self.on_ground:
            # Stick to ground and follow slope by adjusting y target
            self.y = ground - 30
            if want_jump:
                self.on_ground = False
                self.vy = -JUMP_VY
        else:
            self.vy += GRAVITY
            self.y += self.vy
            # Land
            if self.y >= ground - 30:
                self.y = ground - 30
                self.vy = 0.0
                self.on_ground = True

        # Move forward
        self.x += self.vx

        # Finish line
        if self.x >= TRACK_LEN and not self.finished:
            self.finished = True

    def apply_obstacle_effects(self, obstacles, input_jump=False):
        if self.finished:
            return
        # Check immediate vicinity
        for ob in obstacles:
            if abs(ob.x - self.x) > 80:
                continue
            if ob.kind == 'ramp':
                # If overlapping ramp region, auto jump boost once
                if ob.collides(self.x, self.y + 28):
                    if self.on_ground:
                        self.on_ground = False
                        self.vy = - (JUMP_VY * 1.1)
                        self.vx = min(MAX_SPEED, self.vx + 1.0)
            else:
                # Collision: mild bump (slow + lift)
                if ob.collides(self.x, self.y + 28):
                    if self.on_ground:
                        self.vx = max(0, self.vx - 2.2)
                        self.y -= 6
                        self.on_ground = False
                        self.vy = -5.0

    def bot_decide(self, obs_field):
        if not self.is_bot or self.finished:
            return False, False  # throttle, jump
        # Bot logic: aim for speed_bias * MAX_SPEED, jump if obstacle ahead
        target = self.speed_bias * MAX_SPEED
        throttle = (self.vx < target)
        # Look ahead
        ahead_x = self.x + 90 + self.vx * 2.0
        need_jump = False
        for ob in obs_field.items:
            if ob.x < self.x:
                continue
            if ob.x > ahead_x:
                break
            if ob.kind == 'ramp':
                # bots prefer jumping ramps early
                need_jump = (random.random() < (self.jump_bias + 0.1))
                break
            else:
                # rock/log: jump if right ahead
                if (ob.x - self.x) < (60 + self.vx * 1.2):
                    need_jump = (random.random() < self.jump_bias)
                    break
        return throttle, need_jump

    def draw(self):
        # Position wheels and body
        slope = slope_at(self.x)
        angle_deg = math.degrees(math.atan2(-slope, 1.0)) * 0.6  # damp orientation
        # Wheels
        wf_x, wf_y = self.x + 18, self.y + 18
        wb_x, wb_y = self.x - 18, self.y + 18
        self.wheel_f.setAttribute("cx", f"{wf_x}")
        self.wheel_f.setAttribute("cy", f"{wf_y}")
        self.wheel_b.setAttribute("cx", f"{wb_x}")
        self.wheel_b.setAttribute("cy", f"{wb_y}")
        # Body
        self.body.setAttribute("x", f"{self.x - 30}")
        self.body.setAttribute("y", f"{self.y - 10}")
        self.body.setAttribute("transform", f"rotate({angle_deg} {self.x} {self.y})")
        # Label
        self.label.setAttribute("x", f"{self.x}")
        self.label.setAttribute("y", f"{self.y - 28}")

# ------------------------------------------------------------
# UI: Buttons, overlays, HUD
# ------------------------------------------------------------
class Button:
    def __init__(self, x, y, w, h, label, cb, fill="#233246", active_fill="#2f4e75"):
        self.cb = cb
        self.active = False
        self.rect = svg.rect(x=x, y=y, width=w, height=h, rx=18, fill=fill, stroke="#0b1119", stroke_width=3, opacity="0.96")
        self.text = svg.text(label, x=x+w/2, y=y+h/2+14, fill="#eef6ff", font_size="48px", text_anchor="middle")
        LAYER_HUD <= self.rect
        LAYER_HUD <= self.text
        # pointer events
        self.rect.bind("pointerdown", self.down)
        self.rect.bind("pointerup", self.up)
        self.rect.bind("pointerleave", self.up)
        self.text.bind("pointerdown", self.down)
        self.text.bind("pointerup", self.up)
        self.text.bind("pointerleave", self.up)
        self.fill = fill
        self.active_fill = active_fill

    def down(self, ev):
        ev.preventDefault()
        SOUND.unlock()
        self.active = True
        self.rect.setAttribute("fill", self.active_fill)
        if callable(self.cb):
            self.cb("down")

    def up(self, ev):
        ev.preventDefault()
        if self.active:
            self.active = False
            self.rect.setAttribute("fill", self.fill)
            if callable(self.cb):
                self.cb("up")

    def set_opacity(self, a):
        self.rect.setAttribute("opacity", str(a))
        self.text.setAttribute("opacity", str(a))

class HUD:
    def __init__(self):
        self.time_text = svg.text("", x=40, y=60, fill="#d9e7ff", font_size="40px")
        self.speed_text = svg.text("", x=40, y=110, fill="#a6c7ff", font_size="32px")
        self.name_text = svg.text("", x=VPW-40, y=60, fill="#e6f2ff", font_size="40px", text_anchor="end")
        LAYER_HUD <= self.time_text
        LAYER_HUD <= self.speed_text
        LAYER_HUD <= self.name_text

    def update(self, ms, speed, name):
        self.time_text.text = f"Time: {fmt_time_ms(ms)}"
        self.speed_text.text = f"Speed: {speed:0.1f}"
        self.name_text.text = name

class Overlays:
    def __init__(self):
        # Semi-transparent curtain
        self.curtain = svg.rect(x=0, y=0, width=VPW, height=VPH, fill="#0b0e14", opacity="0.0")
        LAYER_OVERLAY <= self.curtain

        self.center_text = svg.text("", x=VPW/2, y=VPH/2, fill="#eaf2ff", font_size="120px", text_anchor="middle")
        LAYER_OVERLAY <= self.center_text

        # Pause Modal
        self.pause_group = svg.g()
        self.pause_bg = svg.rect(x=VPW/2-380, y=VPH/2-220, width=760, height=440, rx=20, fill="#0f1724", stroke="#2a3a58", stroke_width=4, opacity="0.98")
        self.pause_title = svg.text("Paused", x=VPW/2, y=VPH/2-120, fill="#e6f2ff", font_size="72px", text_anchor="middle")
        self.resume_btn = Button(VPW/2-200, VPH/2-40, 400, 100, "Resume", lambda s: Game.instance.toggle_pause() if s=="up" else None)
        self.pause_group <= self.pause_bg
        self.pause_group <= self.pause_title
        LAYER_OVERLAY <= self.pause_group
        self.pause_group.setAttribute("display", "none")

        # Home overlay contents (SVG)
        self.title = svg.text("Camcookie Dirt Dash", x=VPW/2, y=VPH/2-200, fill="#e6f2ff", font_size="96px", text_anchor="middle")
        LAYER_OVERLAY <= self.title
        # We'll add HTML input + start button overlayed via absolute positioning (created in Game)

        # Results modal
        self.results_group = svg.g()
        self.results_bg = svg.rect(x=VPW/2-520, y=120, width=1040, height=800, rx=20, fill="#0f1724", stroke="#2a3a58", stroke_width=4, opacity="0.98")
        self.results_title = svg.text("Results", x=VPW/2, y=200, fill="#e6f2ff", font_size="72px", text_anchor="middle")
        self.results_list = []
        self.results_group <= self.results_bg
        self.results_group <= self.results_title
        LAYER_OVERLAY <= self.results_group
        self.results_group.setAttribute("display", "none")

        # Victory burst
        self.victory_text = svg.text("", x=VPW/2, y=280, fill="#fff3b0", font_size="84px", text_anchor="middle")
        LAYER_OVERLAY <= self.victory_text

    def show_curtain(self, a):
        self.curtain.setAttribute("opacity", str(a))

    def show_pause(self, show=True):
        self.pause_group.setAttribute("display", "block" if show else "none")

    def set_center(self, txt):
        self.center_text.text = txt

    def show_results(self, rows, highlight_name, best_ms=None, player_won=False):
        # Clear previous
        self.results_group.setAttribute("display", "block")
        # Remove old list items
        for n in self.results_list:
            try:
                n.remove()
            except:
                pass
        self.results_list = []
        y = 280
        for i, (name, ms) in enumerate(rows, start=1):
            highlight = (name == highlight_name)
            color = "#fff6cc" if highlight else "#cfe0ff"
            t = svg.text(f"{i}. {name} — {fmt_time_ms(ms)}", x=VPW/2, y=y, fill=color, font_size="46px", text_anchor="middle")
            self.results_group <= t
            self.results_list.append(t)
            y += 58
        y += 20
        if best_ms is not None:
            best = svg.text(f"Best time: {fmt_time_ms(best_ms)}", x=VPW/2, y=y, fill="#a8ffcf", font_size="40px", text_anchor="middle")
            self.results_group <= best
            self.results_list.append(best)
            y += 56
        # Buttons
        self.btn_restart = Button(VPW/2-460, y, 420, 100, "Replay", lambda s: Game.instance.restart() if s=="up" else None)
        self.btn_home = Button(VPW/2+40, y, 420, 100, "Home", lambda s: Game.instance.to_home() if s=="up" else None)
        if player_won:
            self.victory_text.text = "Victory!"
        else:
            self.victory_text.text = ""

    def hide_results(self):
        self.results_group.setAttribute("display", "none")
        self.victory_text.text = ""

# ------------------------------------------------------------
# Game core
# ------------------------------------------------------------
class Game:
    instance = None

    def __init__(self):
        Game.instance = self
        self.state = "home"
        self.name = "Player"
        self.best_time_ms = self._load_best()
        self.camera_x = 0.0

        # Terrain + obstacles
        self.terrain_poly = svg.polygon(points="", fill="#37465e", stroke="#1a2333", stroke_width=2)
        LAYER_TERRAIN <= self.terrain_poly
        self.obs_field = ObstacleField(TRACK_LEN)
        self.obs_field.render(LAYER_OBS)

        # Grid overlay for countdown
        self.grid = self._make_start_grid()
        LAYER_OVERLAY <= self.grid
        self.grid.setAttribute("display", "none")

        # Actors
        self.player = Bike(self.name, color="#7fc8ff", is_bot=False)
        self.bots = []

        # HUD and overlays
        self.hud = HUD()
        self.ui = Overlays()

        # Controls
        self.throttle_down = False
        self.brake_down = False
        self.jump_down = False
        self.engine_on = False
        self.paused = False
        self.muted = MUTE_DEFAULT

        # Buttons
        self._make_buttons()

        # HTML name input + Start button
        self._build_home_ui()

        # Countdown
        self.countdown_start_ms = None

        # Loop
        self._last_t = now_ms()
        self._raf_id = None
        self._loop()

        # Tap anywhere to unlock audio on first interaction
        ROOT.bind("pointerdown", lambda e: SOUND.unlock())

    # ------------- Home UI -------------
    def _build_home_ui(self):
        # HTML container overlaid
        container = document.select_one("#home-ui")
        if container:
            container.remove()
        container = html.DIV(Id="home-ui")
        container.style.position = "absolute"
        container.style.left = "0"
        container.style.top = "0"
        container.style.width = "100vw"
        container.style.height = "100vh"
        container.style.display = "flex"
        container.style.flexDirection = "column"
        container.style.alignItems = "center"
        container.style.justifyContent = "center"
        container.style.gap = "24px"
        container.style.pointerEvents = "auto"

        label = html.DIV("Enter name", Id="name-label")
        label.style.color = "#e6f2ff"
        label.style.fontSize = "28px"
        name_input = html.INPUT(Id="name-input")
        name_input.attrs["placeholder"] = "Your name"
        name_input.style.width = "min(80vw, 560px)"
        name_input.style.height = "64px"
        name_input.style.fontSize = "28px"
        name_input.style.borderRadius = "12px"
        name_input.style.border = "2px solid #2a3a58"
        name_input.style.padding = "0 20px"
        name_input.style.background = "#0f1724"
        name_input.style.color = "#e6f2ff"

        start_btn = html.BUTTON("Start", Id="start-btn")
        start_btn.style.width = "min(80vw, 560px)"
        start_btn.style.height = "72px"
        start_btn.style.fontSize = "30px"
        start_btn.style.borderRadius = "14px"
        start_btn.style.border = "2px solid #2a3a58"
        start_btn.style.background = "#24334a"
        start_btn.style.color = "#e6f2ff"
        start_btn.bind("click", lambda e: self.start_race())

        mute_toggle = html.BUTTON("Mute: Off" if not self.muted else "Mute: On", Id="mute-btn")
        mute_toggle.style.width = "min(80vw, 560px)"
        mute_toggle.style.height = "56px"
        mute_toggle.style.fontSize = "22px"
        mute_toggle.style.borderRadius = "12px"
        mute_toggle.style.border = "2px solid #2a3a58"
        mute_toggle.style.background = "#172234"
        mute_toggle.style.color = "#bcd3ff"
        def toggle_mute(ev):
            self.muted = not self.muted
            SOUND.set_mute(self.muted)
            mute_toggle.text = "Mute: On" if self.muted else "Mute: Off"
        mute_toggle.bind("click", toggle_mute)

        container <= label
        container <= name_input
        container <= start_btn
        container <= mute_toggle

        document <= container
        self.home_dom = container
        self.name_input = name_input
        self.ui.title.text = "Camcookie Dirt Dash"
        self.ui.show_curtain(0.55)
        self.ui.set_center("")

    # ------------- Buttons -------------
    def _make_buttons(self):
        # Right cluster (throttle, jump, engine)
        pad = 24
        btn_w, btn_h = 280, 140
        # Lower right
        self.btn_throttle = Button(VPW - btn_w - pad, VPH - btn_h - pad, btn_w, btn_h, "▶", self._on_throttle)
        # Upper right
        self.btn_jump = Button(VPW - btn_w - pad, VPH - 2*btn_h - 2*pad, btn_w, btn_h, "⤴", self._on_jump)
        # Engine toggle top-right small
        self.btn_engine = Button(VPW - btn_w - pad, pad, btn_w, 110, "Engine", self._on_engine)
        self.btn_engine.text.setAttribute("y", f"{pad + 72}")

        # Left cluster (brake, pause)
        self.btn_brake = Button(pad, VPH - btn_h - pad, btn_w, btn_h, "◀", self._on_brake)
        self.btn_pause = Button(pad, pad, 220, 110, "Pause", self._on_pause)

        # Lower opacity on desktop (optional)
        is_touch = "ontouchstart" in window
        if not is_touch:
            for b in [self.btn_throttle, self.btn_brake, self.btn_jump, self.btn_engine, self.btn_pause]:
                b.set_opacity(0.85)

    def _on_throttle(self, phase):
        if self.state != "running": return
        self.throttle_down = (phase == "down")
        if phase == "up":
            SOUND.click()

    def _on_brake(self, phase):
        if self.state != "running": return
        self.brake_down = (phase == "down")
        if phase == "up":
            SOUND.click()

    def _on_jump(self, phase):
        if self.state != "running": return
        if phase == "down":
            self.jump_down = True
        if phase == "up":
            SOUND.click()
    def _on_engine(self, phase):
        if phase == "up":
            # Toggle engine only during countdown/running/paused
            if self.state in ("countdown", "running", "paused"):
                self.engine_on = not self.engine_on
                if self.engine_on and self.state == "running":
                    SOUND.engine_on()
                else:
                    SOUND.engine_off()
                self._refresh_engine_button()
                SOUND.click()

    def _refresh_engine_button(self):
        # Visual hint for engine state
        label = "Engine: On" if self.engine_on else "Engine: Off"
        self.btn_engine.text.text = label
        self.btn_engine.rect.setAttribute("fill", "#2f4e75" if self.engine_on else "#233246")

    def _on_pause(self, phase):
        if phase == "up":
            if self.state == "running":
                self.toggle_pause()
                SOUND.click()
            elif self.state == "paused":
                self.toggle_pause()
                SOUND.click()

    def toggle_pause(self):
        if self.state == "running":
            self.state = "paused"
            self.paused = True
            self.ui.show_pause(True)
            self.ui.show_curtain(0.55)
            SOUND.engine_off()
        elif self.state == "paused":
            self.state = "running"
            self.paused = False
            self.ui.show_pause(False)
            self.ui.show_curtain(0.0)
            if self.engine_on:
                SOUND.engine_on()

    # ------------- Start grid -------------
    def _make_start_grid(self):
        g = svg.g()
        # faint grid/checkers near the starting area
        cell = 40
        cols = int(VPW / cell) + 2
        rows = int(240 / cell) + 2
        y0 = GROUND_Y - 160
        for r in range(rows):
            for c in range(cols):
                x = c * cell
                y = y0 + r * cell
                if (r + c) % 2 == 0:
                    sq = svg.rect(x=x, y=y, width=cell, height=cell, fill="#1a2333", opacity="0.35")
                    g <= sq
        # start line
        line = svg.rect(x=0, y=terrain_y(0) - 140, width=14, height=280, fill="#d9e7ff", opacity="0.65")
        g <= line
        return g

    # ------------- Home / Race flow -------------
    def start_race(self):
        # Read name and init
        nm = (self.name_input.value or "").strip()
        self.name = nm if nm else "Player"
        self.player.name = self.name
        self.player.label.text = self.name

        # Hide home UI
        if getattr(self, "home_dom", None):
            self.home_dom.style.display = "none"

        # Reset world
        self.to_start_state()

        # Countdown
        self._begin_countdown()

    def to_start_state(self):
        # Reset terrain/actors/obstacles where needed
        self.player.reset()
        # Bots fresh
        for b in self.bots:
            try:
                b.group.remove()
            except:
                pass
        self.bots = []
        palette = ["#ffa07a", "#a2ff9c", "#ffda7f", "#caa0ff", "#9fe0ff"]
        for i in range(BOT_COUNT):
            bot = Bike(f"Bot {i+1}", color=palette[i % len(palette)], is_bot=True)
            self.bots.append(bot)

        # Reset times and state
        self.finish_announced = False
        self.race_start_ms = None
        self.countdown_start_ms = None
        self.camera_x = 0.0
        self.state = "countdown"
        self.paused = False

        # Visuals
        self.grid.setAttribute("display", "block")
        self.ui.set_center("")
        self.ui.show_curtain(0.35)
        self.ui.hide_results()
        self._refresh_engine_button()

    def _begin_countdown(self):
        self.countdown_start_ms = now_ms()
        # Prime engine sound state but do not start hum until running
        SOUND.engine_off()
        # Beeps on 3,2,1,GO
        SOUND.countdown_beep(False)

    def _start_running(self):
        self.state = "running"
        self.race_start_ms = now_ms()
        self.ui.set_center("")
        self.ui.show_curtain(0.0)
        self.grid.setAttribute("display", "none")
        if self.engine_on:
            SOUND.engine_on()

    def restart(self):
        # Called from Results
        self.to_start_state()
        self._begin_countdown()

    def to_home(self):
        # Stop race and return to home UI
        self.state = "home"
        self.paused = False
        SOUND.engine_off()
        self.ui.show_curtain(0.55)
        self.grid.setAttribute("display", "none")
        self.ui.hide_results()
        if getattr(self, "home_dom", None):
            self.home_dom.style.display = "flex"

    # ------------- Camera and rendering -------------
    def _update_camera(self):
        # Keep player ~40% from left
        target = self.player.x - VPW * 0.4
        target = clamp(target, 0, TRACK_LEN - VPW * 0.2)
        self.camera_x += (target - self.camera_x) * CAM_EASE

    def _set_layers_transform(self):
        tx = -self.camera_x
        for layer in (LAYER_TERRAIN, LAYER_OBS, LAYER_ACTORS):
            layer.setAttribute("transform", f"translate({tx}, 0)")

    def _render_terrain(self):
        # Build polygon across visible range
        margin = 200
        x0 = int(max(0, self.camera_x - margin))
        x1 = int(min(TRACK_LEN + 4, self.camera_x + VPW + margin))
        pts = []
        step = TERRAIN_STEP
        for x in range(x0, x1, step):
            pts.append(f"{x},{terrain_y(x)}")
        # Close to bottom
        pts.append(f"{x1},{terrain_y(x1-1)}")
        pts.append(f"{x1},{VPH}")
        pts.append(f"{x0},{VPH}")
        self.terrain_poly.setAttribute("points", " ".join(pts))

    # ------------- Core update step -------------
    def _step(self, dt_ms):
        if self.state == "home":
            # no simulation
            return

        # Handle countdown
        if self.state == "countdown":
            elapsed = now_ms() - self.countdown_start_ms
            # Show 3-2-1-GO
            remaining = COUNTDOWN_MS - elapsed
            if remaining > 800:
                self.ui.set_center("3")
            elif remaining > 1600 - 800:
                self.ui.set_center("2")
                # Beep once on change
                if 1600 <= elapsed < 1700:
                    SOUND.countdown_beep(False)
            elif remaining > 800 - 800:
                self.ui.set_center("1")
                if 2400 <= elapsed < 2500:
                    SOUND.countdown_beep(False)
            elif remaining > 0:
                self.ui.set_center("GO!")
                if 3200 <= elapsed < 3400:
                    SOUND.countdown_beep(True)
            else:
                self._start_running()

        if self.state != "running":
            return

        # Determine inputs
        throttle = self.throttle_down and self.engine_on
        brake = self.brake_down
        want_jump = self.jump_down
        self.jump_down = False  # one-shot

        # Player physics and obstacles
        self.player.update_physics(dt_ms, throttle, brake, want_jump)
        self.player.apply_obstacle_effects(self.obs_field.items, want_jump)

        # Bots
        for b in self.bots:
            t_on, j_on = b.bot_decide(self.obs_field)
            b.update_physics(dt_ms, t_on, False, j_on)
            b.apply_obstacle_effects(self.obs_field.items, j_on)

        # Finish times
        self._check_finish_state()

        # Camera and sound
        self._update_camera()
        if self.engine_on:
            SOUND.engine_set_speed(self.player.vx)
        else:
            SOUND.engine_off()

    def _check_finish_state(self):
        # Mark finish times
        if self.race_start_ms is None:
            return
        tnow = now_ms()
        # Player
        if self.player.finished and self.player.finish_time_ms is None:
            self.player.finish_time_ms = tnow - self.race_start_ms
        # Bots
        for b in self.bots:
            if b.finished and b.finish_time_ms is None:
                b.finish_time_ms = tnow - self.race_start_ms

        # If all finished, show results
        if self._all_finished():
            self._show_results()

    def _all_finished(self):
        if not self.player.finished:
            return False
        for b in self.bots:
            if not b.finished:
                return False
        return True

    def _show_results(self):
        if self.finish_announced:
            return
        self.finish_announced = True
        self.state = "results"
        SOUND.engine_off()

        # Gather and sort
        rows = self._gather_results()
        player_place = 1 + [n for n, _ in rows].index(self.player.name)
        player_won = (player_place == 1)

        # Best time
        if self.player.finish_time_ms is not None:
            if self.best_time_ms is None or self.player.finish_time_ms < self.best_time_ms:
                self.best_time_ms = self.player.finish_time_ms
                self._save_best(self.best_time_ms)

        # Show modal
        self.ui.show_curtain(0.55)
        self.ui.show_results(rows, highlight_name=self.player.name, best_ms=self.best_time_ms, player_won=player_won)
        if player_won:
            SOUND.victory()

        # Reparent results buttons into overlay group (so they sit above curtain)
        if hasattr(self.ui, "btn_restart"):
            try:
                self.ui.btn_restart.rect.remove()
                self.ui.btn_restart.text.remove()
                self.ui.results_group <= self.ui.btn_restart.rect
                self.ui.results_group <= self.ui.btn_restart.text
            except:
                pass
        if hasattr(self.ui, "btn_home"):
            try:
                self.ui.btn_home.rect.remove()
                self.ui.btn_home.text.remove()
                self.ui.results_group <= self.ui.btn_home.rect
                self.ui.results_group <= self.ui.btn_home.text
            except:
                pass

    def _gather_results(self):
        res = []
        if self.player.finish_time_ms is None:
            ptime = 9999999
        else:
            ptime = self.player.finish_time_ms
        res.append((self.player.name, ptime))
        for b in self.bots:
            t = b.finish_time_ms if b.finish_time_ms is not None else 9999999
            res.append((b.name, t))
        res.sort(key=lambda x: x[1])
        return res

    # ------------- Storage -------------
    def _load_best(self):
        try:
            ls = window.localStorage
            v = ls.getItem("dirt_dash_best")
            if v is None:
                return None
            return int(v)
        except:
            return None

    def _save_best(self, ms):
        try:
            window.localStorage.setItem("dirt_dash_best", str(int(ms)))
        except:
            pass

    # ------------- Main loop -------------
    def _loop(self):
        t = now_ms()
        dt = t - self._last_t
        self._last_t = t

        if not self.paused:
            self._step(dt)

        # Draw scene
        self._render_terrain()
        for ob in self.obs_field.items:
            ob.update_graphics()
        self.player.draw()
        for b in self.bots:
            b.draw()
        self._set_layers_transform()

        # HUD
        if self.state in ("countdown", "running"):
            elapsed = 0 if self.race_start_ms is None else max(0, t - self.race_start_ms)
            self.hud.update(elapsed, self.player.vx, self.player.name)
        else:
            self.hud.update(0, self.player.vx, self.player.name)

        # Make sure pause resume button is above curtain
        # Reparent resume button into pause group if not done yet
        try:
            if hasattr(self.ui, "resume_btn") and getattr(self, "_resume_btn_moved", False) is not True:
                self.ui.resume_btn.rect.remove()
                self.ui.resume_btn.text.remove()
                self.ui.pause_group <= self.ui.resume_btn.rect
                self.ui.pause_group <= self.ui.resume_btn.text
                self._resume_btn_moved = True
        except:
            pass

        # Next frame
        window.requestAnimationFrame(lambda _ts: self._loop())


# Kick off the game
Game()
from browser import window
window.camcookie_ready = True