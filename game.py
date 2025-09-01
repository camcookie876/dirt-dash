from browser import document, svg, timer, window
import math, json

# =========================
# Config
# =========================
W, H = 1100, 620                     # Matches SVG viewBox in index.html
GROUND_BASE_Y = 470
GRAVITY = 1500.0
JUMP_VY = -540.0
MAX_SPEED = 270.0
ACCEL = 620.0
BRAKE = 980.0
ROLL_DECEL = 720.0
FRAME_DT = 1/60
TRACK_LENGTH = 3600.0

BOT_COUNT_DEFAULT = 3
COUNTDOWN_MS = 3000

OBST_ROCKS = 12
OBST_LOGS = 8
OBST_RAMPS = 8

# =========================
# State
# =========================
state = "HOME"       # HOME, GRID, PLAY, PAUSE, END
keys = set()         # keyboard codes currently pressed
world_x = 0.0
time_elapsed = 0.0
countdown_end_ms = None
results = []
bot_count = BOT_COUNT_DEFAULT
reduced_motion = True

# Inputs (also set by mobile buttons)
inp_throttle = False
inp_brake = False
inp_jump_pressed = False   # edge-trigger
engine_on = False

# =========================
# DOM / SVG Layers
# =========================
root = document["game"]
root.clear()

layers = {
    "sky": svg.g(),
    "bg": svg.g(),
    "far": svg.g(),
    "ground": svg.g(),
    "obstacles": svg.g(),
    "bots": svg.g(),
    "bike": svg.g(),
    "hud": svg.g(),
    "overlay": svg.g(),
    "controls": svg.g()   # on-screen mobile buttons
}
for g in layers.values():
    root <= g

# Optional top bar spans from HTML (won't fail if missing)
status_el = document.getElementById("status")
engine_el = document.getElementById("engine")
rm_el = document.getElementById("rm")

def set_status_txt(txt):
    if status_el: status_el.text = txt

def set_engine_txt(on):
    if engine_el: engine_el.text = "ON" if on else "OFF"

def set_rm_txt(on):
    if rm_el: rm_el.text = "ON" if on else "OFF"

set_status_txt(state)
set_engine_txt(engine_on)
set_rm_txt(reduced_motion)

# =========================
# Background
# =========================
layers["sky"] <= svg.rect(x=0, y=0, width=W, height=H, fill="#21304b")
band1 = svg.rect(x=0, y=H-260, width=W*2, height=260, fill="#1b2438")
band2 = svg.rect(x=0, y=H-200, width=W*2, height=200, fill="#162034")
layers["bg"] <= band1
layers["bg"] <= band2
layers["far"] <= svg.rect(x=0, y=H-150, width=W*2, height=60, fill="#121a2a")

ground_path = svg.polygon(points="", fill="#2C3A4F", stroke="#192235", stroke_width="2")
layers["ground"] <= ground_path

# Start/Finish markers
finish_group = svg.g(); layers["ground"] <= finish_group
start_group = svg.g(); layers["ground"] <= start_group

def build_finish():
    finish_group.clear()
    fx = TRACK_LENGTH
    pole = svg.rect(x=fx, y=H-320, width=6, height=320, fill="#0ea5e9")
    flag = svg.rect(x=fx+6, y=H-320, width=24, height=24, fill="#f8fafc")
    finish_group <= pole
    finish_group <= flag
    for r in range(0, 3):
        for c in range(0, 3):
            if (r+c)%2==0:
                sq = svg.rect(x=fx+6+c*8, y=H-320+r*8, width=8, height=8, fill="#111827")
                finish_group <= sq

def build_start():
    start_group.clear()
    sx = 0
    pole = svg.rect(x=sx, y=H-320, width=6, height=320, fill="#10b981")
    banner = svg.rect(x=sx+6, y=H-320, width=70, height=22, fill="#22d3ee")
    start_group <= pole
    start_group <= banner

build_finish()
build_start()

# =========================
# Math / Track
# =========================
def ground_y_at(xw: float) -> float:
    return (GROUND_BASE_Y
            + 16.0 * math.sin((xw+200)/260.0)
            + 12.0 * math.sin((xw+900)/180.0))

def clamp(v, lo, hi):
    return lo if v < lo else hi if v > hi else v

def fmt_time(t):
    m = int(t // 60)
    s = t - 60*m
    return f"{m}:{s:05.2f}"

def seeded_rand(seed):
    state = {"x": seed & 0x7fffffff}
    def rnd():
        state["x"] = (1103515245*state["x"] + 12345) & 0x7fffffff
        return state["x"] / 0x7fffffff
    return rnd

# =========================
# Obstacles
# =========================
obstacles = []
ob_nodes = []

def spawn_obstacles():
    global obstacles, ob_nodes
    obstacles.clear()
    ob_nodes.clear()
    rnd = seeded_rand(1337)
    # rocks
    for n in range(OBST_ROCKS):
        xw = 240 + (TRACK_LENGTH-480)*(n+1)/(OBST_ROCKS+1) + int(rnd()*53) - 26
        r = 10 + (n*31)%7
        obstacles.append({"type":"rock", "xw": xw, "r": r})
    # logs
    for n in range(OBST_LOGS):
        xw = 400 + (TRACK_LENGTH-800)*(n+1)/(OBST_LOGS+1) + int(rnd()*73) - 36
        w = 56 + (n*13)%16
        h = 12
        obstacles.append({"type":"log", "xw": xw, "w": w, "h": h})
    # ramps
    for n in range(OBST_RAMPS):
        xw = 350 + (TRACK_LENGTH-700)*(n+1)/(OBST_RAMPS+1) + int(rnd()*61) - 30
        w = 84; h = 40
        obstacles.append({"type":"ramp", "xw": xw, "w": w, "h": h})
    obstacles.sort(key=lambda o: o["xw"])

    layers["obstacles"].clear()
    for ob in obstacles:
        if ob["type"] == "rock":
            g = svg.g()
            c = svg.circle(cx=0, cy=0, r=ob["r"], fill="#7dd3fc", stroke="#0ea5e9", stroke_width="2")
            g <= c
        elif ob["type"] == "log":
            g = svg.g()
            rect = svg.rect(x=0, y=0, width=ob["w"], height=ob["h"], fill="#a78b6a", stroke="#6b4f33", stroke_width="2")
            g <= rect
        else:
            g = svg.g()
            tri = svg.polygon(points=f"0,0 {ob['w']},0 0,-{ob['h']}", fill="#9ca3af", stroke="#6b7280", stroke_width="2")
            g <= tri
        layers["obstacles"] <= g
        ob_nodes.append((ob, g))

def draw_obstacles(scroll_x):
    for ob, node in ob_nodes:
        y = ground_y_at(ob["xw"])
        if ob["type"] == "rock":
            node.setAttribute("transform", f"translate({ob['xw']-scroll_x},{y - ob['r']})")
        elif ob["type"] == "log":
            node.setAttribute("transform", f"translate({ob['xw']-scroll_x - ob['w']/2},{y - ob['h']})")
        else:
            node.setAttribute("transform", f"translate({ob['xw']-scroll_x - ob['w']/2},{y})")

# =========================
# Bikes / Bots
# =========================
class Bike:
    def __init__(self, color="#ffd166", is_bot=False, name="You"):
        self.is_bot = is_bot
        self.name = name
        self.color = color
        self.xw = 0.0
        self.y = ground_y_at(0) - 40
        self.vy = 0.0
        self.speed = 0.0
        self.finished = False
        self.finish_time = None
        self.bump_cooldown = 0.0
        if is_bot:
            self.node = svg.g()
            body = svg.rect(x=0, y=0, width=62, height=18, rx=4, ry=4, fill=color, stroke="#0f172a", stroke_width="2")
            wb = svg.circle(cx=12, cy=26, r=12, fill="none", stroke="#e5e7eb", stroke_width="2")
            wf = svg.circle(cx=50, cy=26, r=12, fill="none", stroke="#e5e7eb", stroke_width="2")
            rd = svg.circle(cx=30, cy=6, r=6, fill="#334155")
            for p in (body, wb, wf, rd): self.node <= p
            layers["bots"] <= self.node

    def on_ground(self):
        return abs(self.y - (ground_y_at(self.xw) - 36)) < 0.15

    def update_physics(self, dt):
        self.vy += GRAVITY * dt
        self.y += self.vy * dt
        floor = ground_y_at(self.xw) - 36
        if self.y >= floor:
            self.y = floor
            self.vy = 0.0
        if self.bump_cooldown > 0:
            self.bump_cooldown -= dt

    def jump(self, vy=JUMP_VY):
        if self.on_ground():
            self.vy = vy

    def draw_player(self, scroll_x):
        sx = (self.xw - scroll_x) + 220
        sy = self.y
        layers["bike"].clear()
        layers["bike"] <= svg.rect(x=sx-30, y=sy-12, width=62, height=18, rx=4, ry=4, fill="#ffd166", stroke="#2b2d42", stroke_width="2")
        layers["bike"] <= svg.circle(cx=sx-18, cy=sy+24, r=12, stroke="#f8fafc", fill="none", stroke_width="3")
        layers["bike"] <= svg.circle(cx=sx+20, cy=sy+24, r=12, stroke="#f8fafc", fill="none", stroke_width="3")
        layers["bike"] <= svg.circle(cx=sx, cy=sy-10, r=6, fill="#e11d48")

    def draw_bot(self, scroll_x):
        if not self.is_bot: return
        tx = f"translate({(self.xw - scroll_x) + 220 - 30},{self.y - 12})"
        self.node.setAttribute("transform", tx)

class BotAI:
    def __init__(self, bike: Bike, target=220.0, jump_bias=0.0, name="Bot"):
        self.bike = bike
        self.target_speed = target
        self.jump_bias = jump_bias
        self.name = name

    def step(self, dt):
        b = self.bike
        if b.finished: return
        # Speed control
        if b.speed < self.target_speed:
            b.speed = min(b.speed + (ACCEL*0.8)*dt, self.target_speed)
        else:
            b.speed = max(b.speed - (ROLL_DECEL*0.4)*dt, self.target_speed*0.9)
        # Look-ahead
        look = 140 + self.jump_bias
        for ob in obstacles:
            if ob["xw"] > b.xw and ob["xw"] - b.xw < look:
                if b.on_ground():
                    if ob["type"] == "ramp":
                        b.jump(JUMP_VY * 0.95)
                    else:
                        b.jump(JUMP_VY * 0.88)
                break
        b.xw += b.speed * dt
        b.update_physics(dt)

# Player and bots
player = Bike()
bots = []
bot_ai = []

# =========================
# HUD / Overlays
# =========================
def draw_ground(scroll_x):
    step = 8
    pts = []
    for sx in range(0, W+step, step):
        xw = scroll_x + sx
        y = ground_y_at(xw)
        pts.append((sx, y))
    pts_ext = pts + [(W, H), (0, H)]
    ground_path.setAttribute("points", " ".join(f"{x},{y}" for x,y in pts_ext))

def draw_finish_start(scroll_x):
    # Translate groups instead of rebuilding
    finish_group.setAttribute("transform", f"translate({-scroll_x},0)")
    start_group.setAttribute("transform", f"translate({-scroll_x},0)")

def draw_obstacles_scroll(scroll_x):
    draw_obstacles(scroll_x)

def draw_hud():
    layers["hud"].clear()
    layers["hud"] <= svg.rect(x=12, y=12, width=460, height=92, rx=10, ry=10, fill="rgba(0,0,0,0.35)")
    layers["hud"] <= svg.text(f"Time {fmt_time(time_elapsed)}", x=24, y=38, fill="#e5e7eb")
    layers["hud"] <= svg.text(f"Speed {int(player.speed)}", x=24, y=64, fill="#e5e7eb")
    # Position
    everyone = [("You", player.xw)] + [(b.name, b.xw) for b in bots]
    everyone.sort(key=lambda t: -t[1])
    pos = next((i+1 for i,(n,_) in enumerate(everyone) if n=="You"), 1)
    layers["hud"] <= svg.text(f"Pos {pos}/{len(everyone)}", x=180, y=64, fill="#e5e7eb")
    layers["hud"] <= svg.text("S engine | → throttle | ← brake", x=320, y=64, fill="#cbd5e1")

def overlay_clear():
    layers["overlay"].clear()

def draw_home():
    overlay_clear()
    p = svg.rect(x=320, y=140, width=480, height=300, rx=12, ry=12, fill="rgba(0,0,0,0.55)", stroke="#0ea5e9", stroke_width="2")
    t = svg.text("Race Setup", x=350, y=180, fill="#f8fafc"); t.setAttribute("style","font-size:24px;font-weight:800")
    info = svg.text("Gentle jumps • Bots • Motion-safe", x=350, y=206, fill="#cbd5e1")
    # Bots +/- and RM toggle
    bc = svg.text(f"Bots: {bot_count}", x=350, y=232, fill="#e5e7eb")
    btn_dec = make_button(430, 216, 28, 28, "–", lambda ev: change_bots(-1))
    btn_inc = make_button(464, 216, 28, 28, "+", lambda ev: change_bots(1))
    btn_rm = make_button(350, 246, 220, 34, f"Reduced Motion: {'ON' if reduced_motion else 'OFF'}", toggle_rm)
    btn_start = make_button(350, 292, 160, 38, "Start Race", lambda ev: start_race())
    for n in (p, t, info, bc, btn_dec, btn_inc, btn_rm, btn_start):
        layers["overlay"] <= n
    # Keep reference to bc to update live
    draw_home.bc_node = bc

def draw_grid():
    overlay_clear()
    ms_left = max(0.0, countdown_end_ms - window.performance.now())
    if ms_left > 0:
        sec = int(ms_left // 1000)
        disp = "3" if sec >= 2 else "2" if sec >= 1 else "1"
    else:
        disp = "GO"
    label = svg.text(disp, x=W/2, y=H/2 - 60, fill="#fde68a")
    label.setAttribute("style","font-size:54px;font-weight:800; text-anchor:middle")
    layers["overlay"] <= label

def draw_pause():
    overlay_clear()
    p = svg.rect(x=400, y=220, width=300, height=140, rx=12, ry=12, fill="rgba(0,0,0,0.55)", stroke="#0ea5e9", stroke_width="2")
    t = svg.text("Paused", x=550, y=260, fill="#f3f4f6"); t.setAttribute("style","font-size:20px;font-weight:800; text-anchor:middle")
    btn = make_button(450, 286, 200, 34, "Resume (P)", lambda ev: pause_toggle())
    for n in (p, t, btn): layers["overlay"] <= n

def draw_end():
    overlay_clear()
    p = svg.rect(x=260, y=120, width=560, height=320, rx=12, ry=12, fill="rgba(0,0,0,0.55)", stroke="#0ea5e9", stroke_width="2")
    t = svg.text("Race Results", x=280, y=160, fill="#f8fafc"); t.setAttribute("style","font-size:22px;font-weight:800")
    layers["overlay"] <= p; layers["overlay"] <= t
    y = 190; pos = 1
    for name, tm in results:
        layers["overlay"] <= svg.text(f"{pos}. {name} — {fmt_time(tm)}", x=280, y=y, fill="#e5e7eb")
        y += 26; pos += 1
    again = make_button(280, y+10, 160, 36, "Race Again (R)", lambda ev: start_race())
    home = make_button(452, y+10, 120, 36, "Home", lambda ev: to_home())
    layers["overlay"] <= again; layers["overlay"] <= home

# =========================
# UI Helpers
# =========================
def make_button(x, y, w, h, label, onclick):
    g = svg.g()
    rect = svg.rect(x=x, y=y, width=w, height=h, rx=8, ry=8, fill="#ffd166")
    txt = svg.text(label, x=x+w/2, y=y+h/2+4, fill="#1f2937")
    txt.setAttribute("style","font-weight:800; text-anchor:middle; font-size:12px")
    g <= rect; g <= txt
    g.bind("click", lambda ev: (ev.preventDefault(), onclick(ev)))
    # Touch-friendly
    g.bind("touchstart", lambda ev: (ev.preventDefault(), onclick(ev)))
    return g

def change_bots(delta):
    global bot_count
    bot_count = max(0, min(5, bot_count + delta))
    if hasattr(draw_home, "bc_node"):
        draw_home.bc_node.text = f"Bots: {bot_count}"

def toggle_rm(ev=None):
    global reduced_motion
    reduced_motion = not reduced_motion
    draw_home() if state == "HOME" else None
    set_rm_txt(reduced_motion)

def pause_toggle():
    global state
    if state == "PLAY":
        state = "PAUSE"
        set_status_txt(state)
        draw_pause()
    elif state == "PAUSE":
        state = "PLAY"
        set_status_txt(state)
        overlay_clear()

# =========================
# Mobile Controls
# =========================
is_touch = bool(getattr(window.navigator, "maxTouchPoints", 0))

# Big on-screen buttons for mobile; desktop can ignore them
def build_controls():
    layers["controls"].clear()
    margin = 12
    bh = 70
    bw = 90
    y = H - margin - bh
    # Left/Right on left side
    left_btn  = control_button(margin, y, bw, bh, "◀", press_left, release_left)
    right_btn = control_button(margin + bw + 10, y, bw, bh, "▶", press_right, release_right)
    # Jump on right side
    jump_btn  = control_button(W - margin - bw, y, bw, bh, "⤴", press_jump, release_jump)
    # Engine toggle and Pause smaller above
    small_w, small_h = 90, 40
    eng_btn = control_button(W - margin - small_w, y - small_h - 8, small_w, small_h, "Engine", toggle_engine, None, momentary=False)
    pau_btn = control_button(W - margin - small_w - 100, y - small_h - 8, small_w, small_h, "Pause", lambda ev: pause_toggle(), None, momentary=False)
    for b in (left_btn, right_btn, jump_btn, eng_btn, pau_btn):
        layers["controls"] <= b
    # Reduce opacity on desktop
    if not is_touch:
        layers["controls"].setAttribute("opacity", "0.25")

def control_button(x, y, w, h, label, on_down, on_up, momentary=True):
    g = svg.g()
    rect = svg.rect(x=x, y=y, width=w, height=h, rx=12, ry=12, fill="#11182799", stroke="#0ea5e9", stroke_width="2")
    txt = svg.text(label, x=x+w/2, y=y+h/2+6, fill="#e5e7eb")
    txt.setAttribute("style","font-size:20px; font-weight:800; text-anchor:middle")
    g <= rect; g <= txt
    # Mouse
    g.bind("mousedown", lambda ev: (ev.preventDefault(), on_down(ev)))
    g.bind("mouseup",   lambda ev: (ev.preventDefault(), (on_up(ev) if on_up else None)))
    g.bind("mouseleave",lambda ev: (ev.preventDefault(), (on_up(ev) if on_up else None)))
    g.bind("click", lambda ev: ev.preventDefault())  # prevent focus scroll
    # Touch
    g.bind("touchstart", lambda ev: (ev.preventDefault(), on_down(ev)))
    g.bind("touchend",   lambda ev: (ev.preventDefault(), (on_up(ev) if on_up else None)))
    g.bind("touchcancel",lambda ev: (ev.preventDefault(), (on_up(ev) if on_up else None)))
    return g

def press_right(ev=None):
    global inp_throttle
    inp_throttle = True

def release_right(ev=None):
    global inp_throttle
    inp_throttle = False

def press_left(ev=None):
    global inp_brake
    inp_brake = True

def release_left(ev=None):
    global inp_brake
    inp_brake = False

def press_jump(ev=None):
    global inp_jump_pressed
    inp_jump_pressed = True

def release_jump(ev=None):
    # nothing; jump is edge-triggered
    pass

def toggle_engine(ev=None):
    global engine_on
    engine_on = not engine_on
    set_engine_txt(engine_on)

# Prevent page scroll on space/arrow on mobile/desktop
def prevent_defaults():
    def stop(ev):
        ev.preventDefault()
    for et in ("touchstart","touchmove","touchend"):
        document.bind(et, stop)
prevent_defaults()

# =========================
# Game Flow
# =========================
def to_home():
    global state
    state = "HOME"
    set_status_txt(state)
    draw_home()

def start_race(ev=None):
    global state, countdown_end_ms, time_elapsed, world_x, engine_on, results
    # reset
    state = "GRID"
    set_status_txt(state)
    results = []
    time_elapsed = 0.0
    world_x = 0.0
    engine_on = False
    player.xw = 0.0
    player.y = ground_y_at(0) - 40
    player.vy = 0.0
    player.speed = 0.0
    player.finished = False
    player.finish_time = None
    # obstacles / bots
    spawn_obstacles()
    build_bots()
    countdown_end_ms = window.performance.now() + COUNTDOWN_MS

def build_bots():
    global bots, bot_ai
    bots = []
    bot_ai = []
    colors = ["#93c5fd", "#86efac", "#fca5a5", "#f0abfc", "#fde68a"]
    layers["bots"].clear()
    for i in range(bot_count):
        b = Bike(color=colors[i % len(colors)], is_bot=True, name=f"Bot {i+1}")
        bots.append(b)
        bot_ai.append(BotAI(b, target=220.0 + 12*i, jump_bias=10*i, name=b.name))

def end_race():
    global state, results
    everyone = []
    for b in [player] + bots:
        t = b.finish_time if b.finish_time is not None else time_elapsed
        everyone.append((b.name, t))
    everyone.sort(key=lambda t: t[1])
    results = everyone
    state = "END"
    set_status_txt(state)
    draw_end()

# =========================
# Collision / Interactions
# =========================
def handle_obstacles(bike: Bike):
    for ob in obstacles:
        dx = ob["xw"] - bike.xw
        if -30 <= dx <= 30:
            gy = ground_y_at(ob["xw"])
            if ob["type"] == "rock":
                top = gy - ob["r"]
                if bike.y >= top - 10 and bike.bump_cooldown <= 0:
                    bike.speed = max(bike.speed * 0.6, bike.speed - 80)
                    bike.vy = -120
                    bike.bump_cooldown = 0.6
            elif ob["type"] == "log":
                top = gy - ob["h"]
                if bike.y >= top - 10 and bike.bump_cooldown <= 0:
                    bike.speed = max(bike.speed * 0.7, bike.speed - 90)
                    bike.vy = -150
                    bike.bump_cooldown = 0.6
            else:
                # ramp: give lift at mouth if on ground
                mouth_left = ob["xw"] - ob["w"]/2
                mouth_right = ob["xw"] + ob["w"]/2
                if mouth_left - 10 <= bike.xw <= mouth_right + 10 and bike.on_ground():
                    bike.vy = JUMP_VY * 0.9

# =========================
# Input (Keyboard)
# =========================
def on_keydown(ev):
    global inp_jump_pressed, engine_on
    code = ev.code
    keys.add(code)
    if code in ("ArrowUp","ArrowDown","ArrowLeft","ArrowRight","Space"):
        ev.preventDefault()
    if code == "Space" and state == "PLAY":
        inp_jump_pressed = True
    elif code == "KeyS":
        engine_on = not engine_on
        set_engine_txt(engine_on)
    elif code == "KeyP":
        pause_toggle()
    elif code == "Enter":
        if state == "HOME":
            start_race()
        elif state == "END":
            start_race()

def on_keyup(ev):
    code = ev.code
    if code in keys:
        keys.remove(code)

document.bind("keydown", on_keydown)
document.bind("keyup", on_keyup)

# =========================
# Main Loop
# =========================
last_ms = window.performance.now()

def loop():
    global last_ms, world_x, time_elapsed, state, inp_jump_pressed
    now = window.performance.now()
    dt = (now - last_ms) / 1000.0
    last_ms = now
    dt = min(dt, 1/30)  # clamp big frame stalls

    # Parallax
    par = 0.15 if reduced_motion else 0.3
    band1.setAttribute("transform", f"translate({-(world_x*par)%W},0)")
    band2.setAttribute("transform", f"translate({-(world_x*(par*1.4))%W},0)")

    if state == "GRID":
        draw_grid()
        if now >= countdown_end_ms:
            state = "PLAY"
            set_status_txt(state)
            # Auto-engine on when race starts
            toggle_engine()
            overlay_clear()

    if state == "PLAY":
        # Inputs
        throttle = inp_throttle or ("ArrowRight" in keys)
        brake = inp_brake or ("ArrowLeft" in keys)

        # Engine behavior
        if not engine_on:
            player.speed = max(0.0, player.speed - ROLL_DECEL*dt)
        else:
            if throttle:
                player.speed = clamp(player.speed + ACCEL*dt, 0, MAX_SPEED)
            elif brake:
                player.speed = clamp(player.speed - BRAKE*dt, 0, MAX_SPEED)
            else:
                player.speed = clamp(player.speed - ROLL_DECEL*dt, 0, MAX_SPEED)

        # Jump (edge-triggered)
        if inp_jump_pressed:
            player.jump()
            inp_jump_pressed = False

        # Advance player
        player.xw += player.speed * dt
        player.update_physics(dt)

        # Bots AI
        for ai in bot_ai:
            ai.step(dt)

        # Collisions
        handle_obstacles(player)

        # Finish checks
        everyone = [player] + bots
        for b in everyone:
            if not b.finished and b.xw >= TRACK_LENGTH:
                b.finished = True
                b.finish_time = time_elapsed
        if all(b.finished or b.xw >= TRACK_LENGTH for b in everyone):
            end_race()

        time_elapsed += dt

    # Camera smoothing
    cam_gain = 0.12 if reduced_motion else 0.2
    world_x += (player.xw - world_x) * cam_gain

    # Draw world
    draw_ground(world_x)
    draw_finish_start(world_x)
    draw_obstacles_scroll(world_x)
    player.draw_player(world_x)
    for b in bots:
        b.draw_bot(world_x)
    draw_hud()

    # Overlays for non-play states
    if state == "HOME":
        draw_home()
    elif state == "PAUSE":
        draw_pause()
    elif state == "END":
        draw_end()

timer.set_interval(loop, int(FRAME_DT*1000))

# Build controls (visible on touch; faint on desktop)
build_controls()

# Start at Home
to_home()