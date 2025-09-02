// Camcookie Dirt Dash — vanilla JS port (SVG + WebAudio)
// No Brython. All logic here.
// Features: splash ready handshake, home screen with name input, mobile-first controls,
// terrain, physics, obstacles/ramps, simple bots, pause, results, local best time, sounds.

(() => {
  "use strict";

  // -------------------- Config --------------------
  const VPW = 1920, VPH = 1080;
  const GROUND_Y = 720;
  const TRACK_LEN = 4000;
  const TERRAIN_STEP = 16;
  const GRAVITY = 0.6;
  const JUMP_VY = 16.0;
  const MAX_SPEED = 22.0;
  const ACCEL = 0.25;
  const BRAKE = 0.35;
  const FRICTION = 0.01;
  const CAM_EASE = 0.08;
  const BOT_COUNT = 3;
  const COUNTDOWN_MS = 3200;
  const OBSTACLE_SPACING = [280, 520];
  const MUTE_DEFAULT = false;

  // -------------------- Helpers --------------------
  const clamp = (v, lo, hi) => v < lo ? lo : (v > hi ? hi : v);
  const nowMs = () => performance.now();
  const fmtTimeMs = (ms) => (ms / 1000).toFixed(2) + "s";
  const randInt = (a,b) => Math.floor(Math.random()*(b-a+1))+a;

  // -------------------- WebAudio --------------------
  class SoundEngine {
    constructor() {
      this.ctx = null;
      this.unlocked = false;
      this.muted = MUTE_DEFAULT;
      this.engineNodes = null;
      this.engineOnFlag = false;
      this.engineHz = 0;
      this.engineTargetHz = 0;
    }
    ensureContext() {
      if (this.ctx) return;
      const AC = window.AudioContext || window.webkitAudioContext;
      if (AC) this.ctx = new AC();
    }
    unlock() {
      this.ensureContext();
      if (!this.ctx || this.unlocked) return;
      this.ctx.resume?.();
      this.unlocked = true;
    }
    setMute(flag) {
      this.muted = flag;
      if (flag) this.engineOff();
    }
    click() {
      if (!this.ready()) return;
      this.beep(660, 0.04, 0.02);
    }
    countdownBeep(last=false) {
      if (!this.ready()) return;
      this.beep(last ? 880 : 440, 0.12, 0.02);
    }
    victory() {
      if (!this.ready()) return;
      const seq = [660, 880, 990, 1320];
      let t0 = this.ctx.currentTime;
      seq.forEach((f,i)=>this.beep(f, 0.12, 0.03, t0 + i*0.13));
    }
    ready() { return this.unlocked && this.ctx && !this.muted; }
    engineOn() {
      if (!this.ready()) { this.engineOnFlag = false; return; }
      if (this.engineNodes) { this.engineOnFlag = true; return; }
      this.engineOnFlag = true;
      const o = this.ctx.createOscillator();
      const g = this.ctx.createGain();
      const lp = this.ctx.createBiquadFilter();
      o.type = "sawtooth";
      o.frequency.value = 0;
      g.gain.value = 0.0001;
      lp.type = "lowpass";
      lp.frequency.value = 600;
      o.connect(lp); lp.connect(g); g.connect(this.ctx.destination);
      o.start();
      this.engineNodes = { o, g, lp };
    }
    engineOff() {
      this.engineOnFlag = false;
      if (!this.engineNodes) return;
      const { o, g } = this.engineNodes;
      try { g.gain.linearRampToValueAtTime(0.0001, this.ctx.currentTime + 0.15); } catch(e){}
      setTimeout(()=>{ try { o.stop(); } catch(e){} }, 300);
      this.engineNodes = null;
    }
    engineSetSpeed(speed) {
      if (!this.engineNodes || !this.engineOnFlag) return;
      const { o, g } = this.engineNodes;
      const hz = clamp(40 + speed * 12, 40, 320);
      this.engineTargetHz = hz;
      this.engineHz += (this.engineTargetHz - this.engineHz) * 0.2;
      try { o.frequency.setTargetAtTime(this.engineHz, this.ctx.currentTime, 0.05); }
      catch(e){ o.frequency.value = this.engineHz; }
      const tgt = 0.04 + (speed / MAX_SPEED) * 0.1;
      try { g.gain.setTargetAtTime(tgt, this.ctx.currentTime, 0.08); }
      catch(e){ g.gain.value = tgt; }
    }
    beep(freq, dur, ramp, startTime=null) {
      this.ensureContext();
      if (!this.ctx) return;
      const t0 = startTime ?? this.ctx.currentTime;
      const o = this.ctx.createOscillator();
      const g = this.ctx.createGain();
      o.type = "sine";
      o.frequency.value = freq;
      g.gain.value = 0.0001;
      o.connect(g); g.connect(this.ctx.destination);
      o.start(t0);
      try {
        g.gain.linearRampToValueAtTime(0.12, t0 + ramp);
        g.gain.linearRampToValueAtTime(0.0001, t0 + dur);
      } catch(e){}
      setTimeout(()=>{ try { o.stop(); } catch(e){} }, (dur+0.05)*1000);
    }
  }
  const SOUND = new SoundEngine();

  // -------------------- SVG / DOM --------------------
  const SVGNS = "http://www.w3.org/2000/svg";
  const rootSvg = document.getElementById("game");
  // Background gradient
  const defs = document.createElementNS(SVGNS, "defs");
  const grad = document.createElementNS(SVGNS, "linearGradient");
  grad.setAttribute("id","sky"); grad.setAttribute("x1","0%"); grad.setAttribute("y1","0%"); grad.setAttribute("x2","0%"); grad.setAttribute("y2","100%");
  const s1 = document.createElementNS(SVGNS, "stop"); s1.setAttribute("offset","0%"); s1.setAttribute("stop-color","#0e1a2b");
  const s2 = document.createElementNS(SVGNS, "stop"); s2.setAttribute("offset","60%"); s2.setAttribute("stop-color","#16253b");
  const s3 = document.createElementNS(SVGNS, "stop"); s3.setAttribute("offset","100%"); s3.setAttribute("stop-color","#1d2130");
  grad.append(s1,s2,s3); defs.appendChild(grad); rootSvg.appendChild(defs);
  const bgRect = document.createElementNS(SVGNS, "rect");
  bgRect.setAttribute("x",0); bgRect.setAttribute("y",0); bgRect.setAttribute("width",VPW); bgRect.setAttribute("height",VPH);
  bgRect.setAttribute("fill","url(#sky)"); rootSvg.appendChild(bgRect);

  // Layers
  const LAYER_BG = document.createElementNS(SVGNS, "g");
  const LAYER_TERRAIN = document.createElementNS(SVGNS, "g");
  const LAYER_OBS = document.createElementNS(SVGNS, "g");
  const LAYER_ACTORS = document.createElementNS(SVGNS, "g");
  const LAYER_HUD = document.createElementNS(SVGNS, "g");
  const LAYER_OVERLAY = document.createElementNS(SVGNS, "g");
  [LAYER_BG, LAYER_TERRAIN, LAYER_OBS, LAYER_ACTORS, LAYER_HUD, LAYER_OVERLAY].forEach(g=>rootSvg.appendChild(g));
  LAYER_BG.appendChild(bgRect);

  // Global UI prevention
  document.addEventListener("contextmenu", e=>e.preventDefault());
  document.documentElement.style.userSelect = "none";

  // -------------------- Terrain --------------------
  function terrainY(x) {
    return (GROUND_Y
      + 90 * Math.sin((x + 300) / 260.0)
      + 48 * Math.sin((x + 800) / 110.0)
      + 24 * Math.sin((x - 1200) / 55.0));
  }
  function slopeAt(x, dx=1.0) {
    const y1 = terrainY(x - dx);
    const y2 = terrainY(x + dx);
    return (y2 - y1) / (2*dx);
  }

  // -------------------- Obstacles --------------------
  class Obstacle {
    constructor(kind, x) {
      this.kind = kind;
      this.x = x;
      this.y = terrainY(x);
      this.node = null;
    }
    render(group) {
      if (this.node) { this.updateGraphics(); return; }
      if (this.kind === "rock") {
        this.node = document.createElementNS(SVGNS, "circle");
        this.node.setAttribute("r", 18);
        this.node.setAttribute("fill", "#7d7f86");
        this.node.setAttribute("stroke", "#2f3138");
        this.node.setAttribute("stroke-width", 3);
      } else if (this.kind === "log") {
        this.node = document.createElementNS(SVGNS, "rect");
        this.node.setAttribute("width", 54);
        this.node.setAttribute("height", 20);
        this.node.setAttribute("rx", 6);
        this.node.setAttribute("fill", "#6b4b2a");
        this.node.setAttribute("stroke", "#3e2a17");
        this.node.setAttribute("stroke-width", 3);
      } else {
        this.node = document.createElementNS(SVGNS, "polygon");
        this.node.setAttribute("fill", "#d1a14f");
        this.node.setAttribute("stroke", "#6a4c20");
        this.node.setAttribute("stroke-width", 3);
      }
      group.appendChild(this.node);
      this.updateGraphics();
    }
    updateGraphics() {
      const y = this.y;
      if (this.kind === "rock") {
        this.node.setAttribute("cx", this.x);
        this.node.setAttribute("cy", y - 20);
      } else if (this.kind === "log") {
        this.node.setAttribute("x", this.x - 28);
        this.node.setAttribute("y", y - 22);
      } else {
        const w=100, h=60;
        const pts = `${this.x-10},${y} ${this.x+w},${y} ${this.x+w},${y-h}`;
        this.node.setAttribute("points", pts);
      }
    }
    collides(px, py) {
      const y = this.y;
      if (this.kind === "rock") {
        const dx = px - this.x;
        const dy = (py - 20) - (y - 20);
        return (dx*dx + dy*dy) < (24*24);
      } else if (this.kind === "log") {
        return (this.x - 28 <= px && px <= this.x + 26) && (y - 22 <= py && py <= y - 2);
      } else {
        return (this.x - 10 <= px && px <= this.x + 100) && (py >= y - 64 && py <= y);
      }
    }
  }
  class ObstacleField {
    constructor(length) { this.length = length; this.items = []; this.generate(); }
    generate() {
      let x = 400;
      while (x < this.length - 200) {
        x += randInt(...OBSTACLE_SPACING);
        const kind = ["rock", "log", "ramp", "rock", "log"][randInt(0,4)];
        this.items.push(new Obstacle(kind, x));
      }
    }
    render(group) { this.items.forEach(o=>o.render(group)); }
  }

  // -------------------- Bike / Actor --------------------
  class Bike {
    constructor(name, color="#7fc8ff", isBot=false) {
      this.name = name; this.color = color; this.isBot = isBot;
      this.reset();
      this.group = document.createElementNS(SVGNS,"g");
      this.body = document.createElementNS(SVGNS,"rect");
      this.body.setAttribute("width",60); this.body.setAttribute("height",20);
      this.body.setAttribute("rx",8); this.body.setAttribute("fill",color);
      this.body.setAttribute("stroke","#1b2a38"); this.body.setAttribute("stroke-width",3);
      this.wheelF = document.createElementNS(SVGNS,"circle");
      this.wheelB = document.createElementNS(SVGNS,"circle");
      [this.wheelF, this.wheelB].forEach(w => { w.setAttribute("r",14); w.setAttribute("fill","#222831"); w.setAttribute("stroke","#0d1116"); w.setAttribute("stroke-width",2); });
      this.label = document.createElementNS(SVGNS,"text");
      this.label.textContent = this.name; this.label.setAttribute("fill","#e6f2ff");
      this.label.setAttribute("font-size","22px"); this.label.setAttribute("text-anchor","middle");
      this.group.append(this.body, this.wheelF, this.wheelB, this.label);
      LAYER_ACTORS.appendChild(this.group);
    }
    reset() {
      this.x = 40;
      this.y = terrainY(this.x) - 30;
      this.vx = 0; this.vy = 0;
      this.onGround = true;
      this.finished = false;
      this.finishTimeMs = null;
      if (this.isBot) {
        this.speedBias = Math.random()*(0.88-0.60)+0.60;
        this.jumpBias = Math.random()*(0.85-0.55)+0.55;
      }
    }
    updatePhysics(dtMs, throttle, brake, wantJump) {
      if (this.finished) return;
      if (throttle) this.vx += ACCEL;
      if (brake) this.vx -= BRAKE;
      if (!throttle && !brake) this.vx *= (1 - FRICTION);
      this.vx = clamp(this.vx, 0, MAX_SPEED);

      const ground = terrainY(this.x);
      if (this.onGround) {
        this.y = ground - 30;
        if (wantJump) { this.onGround = false; this.vy = -JUMP_VY; }
      } else {
        this.vy += GRAVITY; this.y += this.vy;
        if (this.y >= ground - 30) { this.y = ground - 30; this.vy = 0; this.onGround = true; }
      }
      this.x += this.vx;
      if (this.x >= TRACK_LEN && !this.finished) this.finished = true;
    }
    applyObstacleEffects(obstacles) {
      if (this.finished) return;
      for (const ob of obstacles) {
        if (Math.abs(ob.x - this.x) > 80) continue;
        if (ob.kind === "ramp") {
          if (ob.collides(this.x, this.y + 28)) {
            if (this.onGround) {
              this.onGround = false; this.vy = -(JUMP_VY*1.1);
              this.vx = Math.min(MAX_SPEED, this.vx + 1.0);
            }
          }
        } else {
          if (ob.collides(this.x, this.y + 28)) {
            if (this.onGround) {
              this.vx = Math.max(0, this.vx - 2.2);
              this.y -= 6; this.onGround = false; this.vy = -5.0;
            }
          }
        }
      }
    }
    botDecide(obsField) {
      if (!this.isBot || this.finished) return [false,false];
      const target = this.speedBias * MAX_SPEED;
      const throttle = (this.vx < target);
      const aheadX = this.x + 90 + this.vx * 2.0;
      let needJump = false;
      for (const ob of obsField.items) {
        if (ob.x < this.x) continue;
        if (ob.x > aheadX) break;
        if (ob.kind === "ramp") {
          needJump = (Math.random() < (this.jumpBias + 0.1)); break;
        } else {
          if ((ob.x - this.x) < (60 + this.vx * 1.2)) {
            needJump = (Math.random() < this.jumpBias); break;
          }
        }
      }
      return [throttle, needJump];
    }
    draw() {
      const slope = slopeAt(this.x);
      const angleDeg = Math.atan2(-slope, 1.0) * 180/Math.PI * 0.6;
      const wf_x = this.x + 18, wf_y = this.y + 18;
      const wb_x = this.x - 18, wb_y = this.y + 18;
      this.wheelF.setAttribute("cx", wf_x); this.wheelF.setAttribute("cy", wf_y);
      this.wheelB.setAttribute("cx", wb_x); this.wheelB.setAttribute("cy", wb_y);
      this.body.setAttribute("x", this.x - 30); this.body.setAttribute("y", this.y - 10);
      this.body.setAttribute("transform", `rotate(${angleDeg} ${this.x} ${this.y})`);
      this.label.setAttribute("x", this.x); this.label.setAttribute("y", this.y - 28);
    }
  }

  // -------------------- UI Widgets --------------------
  class Button {
    constructor(x,y,w,h,label,cb, fill="#233246", active="#2f4e75") {
      this.cb = cb; this.active=false;
      this.rect = document.createElementNS(SVGNS,"rect");
      this.rect.setAttribute("x",x); this.rect.setAttribute("y",y);
      this.rect.setAttribute("width",w); this.rect.setAttribute("height",h);
      this.rect.setAttribute("rx",18); this.rect.setAttribute("fill",fill);
      this.rect.setAttribute("stroke","#0b1119"); this.rect.setAttribute("stroke-width",3);
      this.rect.setAttribute("opacity","0.96");
      this.text = document.createElementNS(SVGNS,"text");
      this.text.textContent = label;
      this.text.setAttribute("x", x+w/2); this.text.setAttribute("y", y+h/2+14);
      this.text.setAttribute("fill","#eef6ff"); this.text.setAttribute("font-size","48px"); this.text.setAttribute("text-anchor","middle");
      LAYER_HUD.append(this.rect, this.text);
      const down = (ev)=>{ ev.preventDefault(); SOUND.unlock(); this.active=true; this.rect.setAttribute("fill", active); cb?.("down"); };
      const up = (ev)=>{ ev.preventDefault(); if (this.active){ this.active=false; this.rect.setAttribute("fill", fill); cb?.("up"); } };
      [this.rect, this.text].forEach(n => {
        n.addEventListener("pointerdown", down);
        n.addEventListener("pointerup", up);
        n.addEventListener("pointerleave", up);
      });
      this.baseFill = fill; this.activeFill = active;
    }
    setOpacity(a){ this.rect.setAttribute("opacity", String(a)); this.text.setAttribute("opacity", String(a)); }
  }
  class HUD {
    constructor() {
      this.timeText = document.createElementNS(SVGNS, "text");
      this.speedText = document.createElementNS(SVGNS, "text");
      this.nameText = document.createElementNS(SVGNS, "text");
      this.timeText.setAttribute("x", 40); this.timeText.setAttribute("y", 60); this.timeText.setAttribute("fill","#d9e7ff"); this.timeText.setAttribute("font-size","40px");
      this.speedText.setAttribute("x", 40); this.speedText.setAttribute("y", 110); this.speedText.setAttribute("fill","#a6c7ff"); this.speedText.setAttribute("font-size","32px");
      this.nameText.setAttribute("x", VPW-40); this.nameText.setAttribute("y", 60); this.nameText.setAttribute("fill","#e6f2ff"); this.nameText.setAttribute("font-size","40px"); this.nameText.setAttribute("text-anchor","end");
      LAYER_HUD.append(this.timeText, this.speedText, this.nameText);
    }
    update(ms, speed, name) {
      this.timeText.textContent = `Time: ${fmtTimeMs(ms)}`;
      this.speedText.textContent = `Speed: ${speed.toFixed(1)}`;
      this.nameText.textContent = name;
    }
  }
  class Overlays {
    constructor() {
      this.curtain = document.createElementNS(SVGNS,"rect");
      this.curtain.setAttribute("x",0); this.curtain.setAttribute("y",0);
      this.curtain.setAttribute("width",VPW); this.curtain.setAttribute("height",VPH);
      this.curtain.setAttribute("fill","#0b0e14"); this.curtain.setAttribute("opacity","0.0");
      LAYER_OVERLAY.appendChild(this.curtain);

      this.centerText = document.createElementNS(SVGNS,"text");
      this.centerText.setAttribute("x", VPW/2); this.centerText.setAttribute("y", VPH/2);
      this.centerText.setAttribute("fill","#eaf2ff"); this.centerText.setAttribute("font-size","120px"); this.centerText.setAttribute("text-anchor","middle");
      LAYER_OVERLAY.appendChild(this.centerText);

      this.pauseGroup = document.createElementNS(SVGNS,"g");
      this.pauseBg = document.createElementNS(SVGNS,"rect");
      this.pauseBg.setAttribute("x", VPW/2-380); this.pauseBg.setAttribute("y", VPH/2-220);
      this.pauseBg.setAttribute("width", 760); this.pauseBg.setAttribute("height", 440); this.pauseBg.setAttribute("rx", 20);
      this.pauseBg.setAttribute("fill", "#0f1724"); this.pauseBg.setAttribute("stroke","#2a3a58"); this.pauseBg.setAttribute("stroke-width",4);
      this.pauseBg.setAttribute("opacity","0.98");
      this.pauseTitle = document.createElementNS(SVGNS,"text");
      this.pauseTitle.textContent = "Paused";
      this.pauseTitle.setAttribute("x", VPW/2); this.pauseTitle.setAttribute("y", VPH/2-120);
      this.pauseTitle.setAttribute("fill","#e6f2ff"); this.pauseTitle.setAttribute("font-size","72px"); this.pauseTitle.setAttribute("text-anchor","middle");
      this.pauseGroup.append(this.pauseBg, this.pauseTitle);
      LAYER_OVERLAY.appendChild(this.pauseGroup);
      this.pauseGroup.setAttribute("display","none");

      this.title = document.createElementNS(SVGNS,"text");
      this.title.textContent = "Camcookie Dirt Dash";
      this.title.setAttribute("x", VPW/2); this.title.setAttribute("y", VPH/2-200);
      this.title.setAttribute("fill","#e6f2ff"); this.title.setAttribute("font-size","96px"); this.title.setAttribute("text-anchor","middle");
      LAYER_OVERLAY.appendChild(this.title);

      this.resultsGroup = document.createElementNS(SVGNS,"g");
      this.resultsBg = document.createElementNS(SVGNS,"rect");
      this.resultsBg.setAttribute("x", VPW/2-520); this.resultsBg.setAttribute("y", 120);
      this.resultsBg.setAttribute("width", 1040); this.resultsBg.setAttribute("height", 800); this.resultsBg.setAttribute("rx", 20);
      this.resultsBg.setAttribute("fill","#0f1724"); this.resultsBg.setAttribute("stroke","#2a3a58"); this.resultsBg.setAttribute("stroke-width",4);
      this.resultsBg.setAttribute("opacity","0.98");
      this.resultsTitle = document.createElementNS(SVGNS,"text");
      this.resultsTitle.textContent = "Results";
      this.resultsTitle.setAttribute("x", VPW/2); this.resultsTitle.setAttribute("y", 200);
      this.resultsTitle.setAttribute("fill","#e6f2ff"); this.resultsTitle.setAttribute("font-size","72px"); this.resultsTitle.setAttribute("text-anchor","middle");
      this.resultsList = [];
      this.resultsGroup.append(this.resultsBg, this.resultsTitle);
      LAYER_OVERLAY.appendChild(this.resultsGroup);
      this.resultsGroup.setAttribute("display","none");

      this.victoryText = document.createElementNS(SVGNS,"text");
      this.victoryText.setAttribute("x", VPW/2); this.victoryText.setAttribute("y", 280);
      this.victoryText.setAttribute("fill","#fff3b0"); this.victoryText.setAttribute("font-size","84px"); this.victoryText.setAttribute("text-anchor","middle");
      LAYER_OVERLAY.appendChild(this.victoryText);
    }
    showCurtain(a){ this.curtain.setAttribute("opacity", String(a)); }
    showPause(show){ this.pauseGroup.setAttribute("display", show ? "block":"none"); }
    setCenter(txt){ this.centerText.textContent = txt || ""; }
    showResults(rows, highlightName, bestMs=null, playerWon=false) {
      this.resultsGroup.setAttribute("display","block");
      this.resultsList.forEach(n=>n.remove()); this.resultsList = [];
      let y = 280;
      rows.forEach(([name, ms], i) => {
        const t = document.createElementNS(SVGNS,"text");
        t.textContent = `${i+1}. ${name} — ${fmtTimeMs(ms)}`;
        t.setAttribute("x", VPW/2); t.setAttribute("y", y);
        t.setAttribute("fill", name===highlightName ? "#fff6cc" : "#cfe0ff");
        t.setAttribute("font-size","46px"); t.setAttribute("text-anchor","middle");
        this.resultsGroup.appendChild(t); this.resultsList.push(t); y += 58;
      });
      y += 20;
      if (bestMs != null) {
        const best = document.createElementNS(SVGNS,"text");
        best.textContent = `Best time: ${fmtTimeMs(bestMs)}`;
        best.setAttribute("x", VPW/2); best.setAttribute("y", y);
        best.setAttribute("fill","#a8ffcf"); best.setAttribute("font-size","40px"); best.setAttribute("text-anchor","middle");
        this.resultsGroup.appendChild(best); this.resultsList.push(best); y += 56;
      }
      this.btnRestart = new Button(VPW/2-460, y, 420, 100, "Replay", s=>{ if (s==="up") window.camcookie.game.restart(); });
      this.btnHome = new Button(VPW/2+40, y, 420, 100, "Home", s=>{ if (s==="up") window.camcookie.game.toHome(); });
      this.victoryText.textContent = playerWon ? "Victory!" : "";
      // Move those two buttons visually atop results group:
      this.resultsGroup.append(this.btnRestart.rect, this.btnRestart.text, this.btnHome.rect, this.btnHome.text);
    }
    hideResults(){ this.resultsGroup.setAttribute("display","none"); this.victoryText.textContent=""; }
  }

  // -------------------- Game core --------------------
  class Game {
    constructor() {
      this.state = "home";
      this.name = "Player";
      this.bestTimeMs = this.loadBest();
      this.cameraX = 0;
      this.paused = false;
      this.engineOn = false;
      this.muted = MUTE_DEFAULT;

      // Terrain
      this.terrainPoly = document.createElementNS(SVGNS,"polygon");
      this.terrainPoly.setAttribute("fill","#37465e"); this.terrainPoly.setAttribute("stroke","#1a2333"); this.terrainPoly.setAttribute("stroke-width",2);
      LAYER_TERRAIN.appendChild(this.terrainPoly);

      // Obstacles
      this.obsField = new ObstacleField(TRACK_LEN);
      this.obsField.render(LAYER_OBS);

      // Start grid
      this.grid = this.makeStartGrid();
      LAYER_OVERLAY.appendChild(this.grid);
      this.grid.setAttribute("display","none");

      // Actors
      this.player = new Bike(this.name, "#7fc8ff", false);
      this.bots = [];

      // HUD and overlays
      this.hud = new HUD();
      this.ui = new Overlays();

      // Inputs
      this.throttleDown=false; this.brakeDown=false; this.jumpDown=false;

      // Buttons
      this.makeButtons();

      // Home UI in HTML
      this.buildHomeUI();

      // Countdown
      this.countdownStartMs = null;
      this.raceStartMs = null;

      // Loop
      this._lastT = nowMs();
      requestAnimationFrame(()=>this.loop());

      // Unlock audio on any pointer
      rootSvg.addEventListener("pointerdown", ()=>SOUND.unlock(), { passive:true });
    }

    buildHomeUI() {
      const cont = document.getElementById("home-ui");
      cont.style.display = "flex";
      cont.innerHTML = "";
      const label = document.createElement("div");
      label.textContent = "Enter name"; label.style.color="#e6f2ff"; label.style.fontSize="24px";
      const input = document.createElement("input"); input.placeholder="Your name";
      const start = document.createElement("button"); start.textContent = "Start Race";
      mute.textContent = this.muted ? "Mute: On" : "Mute: Off";
      mute.addEventListener("click", () => {
        this.muted = !this.muted;
        SOUND.setMute(this.muted);
        mute.textContent = this.muted ? "Mute: On" : "Mute: Off";
      });

      start.addEventListener("click", () => {
        this.name = input.value.trim() || "Player";
        this.player.name = this.name;
        this.player.label.textContent = this.name;
        cont.style.display = "none";
        this.toStartState();
        this.beginCountdown();
      });

      cont.append(label, input, start, mute);
      this.nameInput = input;
    }

    toStartState() {
      this.player.reset();
      this.bots.forEach(b => b.group.remove());
      this.bots = [];
      const palette = ["#ffa07a", "#a2ff9c", "#ffda7f", "#caa0ff", "#9fe0ff"];
      for (let i = 0; i < BOT_COUNT; i++) {
        const bot = new Bike(`Bot ${i + 1}`, palette[i % palette.length], true);
        this.bots.push(bot);
      }

      this.finishAnnounced = false;
      this.raceStartMs = null;
      this.countdownStartMs = null;
      this.cameraX = 0;
      this.state = "countdown";
      this.paused = false;

      this.grid.setAttribute("display", "block");
      this.ui.setCenter("");
      this.ui.showCurtain(0.35);
      this.ui.hideResults();
      this.refreshEngineButton();
    }

    beginCountdown() {
      this.countdownStartMs = nowMs();
      SOUND.engineOff();
      SOUND.countdownBeep(false);
    }

    refreshEngineButton() {
      const label = this.engineOn ? "Engine: On" : "Engine: Off";
      this.btnEngine.text.textContent = label;
      this.btnEngine.rect.setAttribute("fill", this.engineOn ? "#2f4e75" : "#233246");
    }

    startFromSplash() {
      document.getElementById("home-ui").style.display = "flex";
    }
  }

  // Expose game instance and splash trigger
  window.camcookie = {
    game: new Game(),
    startFromSplash: () => window.camcookie.game.startFromSplash()
  };

  // Signal splash screen that game is ready
  window.dispatchEvent(new Event("camcookie-ready"));
})();