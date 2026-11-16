// Render the pond at half scale. A small wave grid drives both reflected light
// and the distortion of the landscape below the waterline.
const HeroWater = (() => {
  const canvas = document.getElementById("heroWater");
  const context = canvas?.getContext("2d");
  if (!context) return null;

  const width = 440;
  const height = 50;
  const columns = 220;
  const waterline = 150;
  const button = document.getElementById("pond-touch");
  const scene = canvas.closest("svg");
  const motion = window.matchMedia("(prefers-reduced-motion: reduce)");
  canvas.width = width;
  canvas.height = height;

  const reflected = document.createElement("canvas");
  reflected.width = width;
  reflected.height = height;
  const reflection = reflected.getContext("2d", { willReadFrequently: true });
  const frame = context.createImageData(width, height);
  let surface = new Float32Array(columns * height);
  let previous = new Float32Array(surface.length);
  const mountains = [...scene.querySelectorAll("#heroHills path")].map(path => ({
    element: path,
    shape: new Path2D(path.getAttribute("d")),
  }));

  // The light source tracks the matching sun or moon in the SVG.
  const skies = {
    dawn: { light: [320, 104, 18], tint: [255, 227, 183], deep: [69, 104, 140], horizon: "#e8b7b4" },
    day: { light: [790, 46, 26], tint: [255, 245, 202], deep: [49, 116, 132], horizon: "#c2e9df" },
    dusk: { light: [730, 122, 21], tint: [255, 185, 121], deep: [58, 67, 104], horizon: "#df9a8a" },
    night: { light: [790, 46, 27], tint: [203, 234, 255], deep: [14, 36, 56], horizon: "#547c9c" },
  };
  let mode;
  let palette;
  let pixels;
  let frameTime = -Infinity;
  let remainder = 0;
  let lightX = 440;
  let lightStrength = 0;
  let pointer = null;
  let previousTouch = null;
  let fade = null;

  function buildReflection() {
    mode = document.documentElement.dataset.sky;
    palette = skies[mode] || skies.day;
    const [sunX, sunY, radius] = palette.light;
    const glowColor = palette.tint.join(",");
    const sky = reflection.createLinearGradient(0, 0, 0, height);
    sky.addColorStop(0, palette.horizon);
    sky.addColorStop(1, `rgb(${palette.deep.join(",")})`);
    reflection.fillStyle = sky;
    reflection.fillRect(0, 0, width, height);

    const x = sunX / 2;
    const y = (waterline - sunY) * 0.36;
    const glow = reflection.createRadialGradient(x, y, 0, x, y, 76);
    glow.addColorStop(0, `rgba(${glowColor}, .95)`);
    glow.addColorStop(.28, `rgba(${glowColor}, .46)`);
    glow.addColorStop(1, `rgba(${glowColor}, 0)`);
    reflection.fillStyle = glow;
    reflection.fillRect(0, 0, width, height);
    reflection.fillStyle = `rgb(${glowColor})`;
    reflection.beginPath();
    reflection.ellipse(x, y, radius / 2, radius * .36, 0, 0, Math.PI * 2);
    reflection.fill();

    reflection.save();
    reflection.setTransform(.5, 0, 0, -.36, 0, waterline * .36);
    reflection.globalAlpha = .52;
    for (const { element, shape } of mountains) {
      reflection.fillStyle = getComputedStyle(element).fill;
      reflection.fill(shape);
    }
    reflection.restore();
    pixels = reflection.getImageData(0, 0, width, height).data;
  }

  function disturb(x, y, strength) {
    if (motion.matches) return;
    const cx = Math.round(x / 4);
    const cy = Math.round((y - waterline) / 2);
    for (let dy = -3; dy <= 3; dy++) {
      const row = cy + dy;
      if (row <= 0 || row >= height - 1) continue;
      for (let dx = -4; dx <= 4; dx++) {
        const col = cx + dx;
        if (col <= 0 || col >= columns - 1) continue;
        const profile = Math.exp(-(dx * dx / 5 + dy * dy / 2.5));
        const index = row * columns + col;
        surface[index] = Math.min(5, surface[index] + strength * profile);
      }
    }
  }

  function propagate() {
    for (let y = 1; y < height - 1; y++) {
      for (let x = 1; x < columns - 1; x++) {
        const i = y * columns + x;
        const edge = Math.min(x, columns - 1 - x, y, height - 1 - y);
        const neighbors = surface[i - 1] + surface[i + 1] + surface[i - columns] + surface[i + columns];
        // Discrete wave equation with an absorbing band around the edges.
        previous[i] = (2 * surface[i] - previous[i] + .43 * (neighbors - 4 * surface[i])) *
          (edge < 5 ? .92 + .013 * edge : .985);
      }
    }
    [surface, previous] = [previous, surface];
  }

  function paint(time) {
    const [red, green, blue] = palette.deep;
    const [lightRed, lightGreen, lightBlue] = palette.tint;
    const sunX = palette.light[0] / 2;
    const data = frame.data;
    const fadeAmount = fade ? Math.max(0, 1 - (time - fade.started) / fade.duration) : 0;
    if (!fadeAmount) fade = null;
    for (let y = 0; y < height; y++) {
      const depth = y / (height - 1);
      const mix = .72 - .42 * depth;
      const offset = y * columns;
      const phase = 20 * Math.log(1 + 3 * depth) - 2.1 * time;
      for (let x = 0; x < width; x++) {
        const col = x >> 1;
        const i = offset + col;
        const normalX = (surface[offset + Math.min(columns - 1, col + 1)] -
          surface[offset + Math.max(0, col - 1)]) * .5;
        const normalY = (surface[Math.min(surface.length - columns + col, i + columns)] -
          surface[Math.max(col, i - columns)]) * .5;
        const breeze = Math.sin(phase + x * .035) * .65 + Math.cos(phase * .84 - x * .051) * .35;
        const sampleX = Math.max(0, Math.min(width - 1, Math.round(x + breeze * (2 + depth * 6) + normalX * 34)));
        const sampleY = Math.max(0, Math.min(height - 1, Math.round(y + breeze * 1.9 + normalY * 16)));
        const reflectedIndex = (sampleY * width + sampleX) * 4;

        const sunDistance = (sampleX - sunX) / (20 + depth * 44);
        const pointerDistance = (x - lightX / 2) / (25 + depth * 39);
        const shimmer = Math.pow(Math.max(0, breeze + normalY * 1.9), 4);
        const light = Math.min(.85, shimmer * (
          .12 + .55 / (1 + sunDistance * sunDistance * 4) +
          lightStrength * .42 / (1 + pointerDistance * pointerDistance * 3)));
        const shade = Math.max(-23, Math.min(23, normalY * 37));
        const p = (y * width + x) * 4;
        data[p] = (pixels[reflectedIndex] * mix + red * (1 - mix) + shade) * (1 - light) + lightRed * light;
        data[p + 1] = (pixels[reflectedIndex + 1] * mix + green * (1 - mix) + shade) * (1 - light) + lightGreen * light;
        data[p + 2] = (pixels[reflectedIndex + 2] * mix + blue * (1 - mix) + shade) * (1 - light) + lightBlue * light;
        if (fade) {
          for (let channel = p; channel < p + 3; channel++) {
            data[channel] += (fade.pixels[channel] - data[channel]) * fadeAmount;
          }
        }
        data[p + 3] = 255;
      }
    }
    context.putImageData(frame, 0, 0);
  }

  function step(dt, time) {
    if (motion.matches) return;
    remainder += dt;
    while (remainder >= 1 / 60) {
      propagate();
      remainder -= 1 / 60;
    }
    if (pointer) lightX += (pointer.x - lightX) * Math.min(1, dt * 7);
    lightStrength += ((pointer ? 1 : 0) - lightStrength) * Math.min(1, dt * 5);
    if (time - frameTime < 1 / 32) return;
    frameTime = time;
    paint(time);
  }

  function scenePoint(event) {
    const matrix = scene.getScreenCTM();
    if (!matrix) return null;
    return new DOMPoint(event.clientX, event.clientY).matrixTransform(matrix.inverse());
  }

  button.addEventListener("pointermove", event => {
    const point = scenePoint(event);
    if (event.pointerType !== "mouse" || !point || point.y < waterline) {
      pointer = null;
      previousTouch = null;
      return;
    }
    pointer = point;
    if (!previousTouch || (event.timeStamp - previousTouch.time > 48 &&
        Math.hypot(point.x - previousTouch.x, point.y - previousTouch.y) > 10)) {
      disturb(point.x, point.y, .62);
      previousTouch = { x: point.x, y: point.y, time: event.timeStamp };
    }
  });
  button.addEventListener("pointerleave", () => {
    pointer = null;
    previousTouch = null;
  });
  button.addEventListener("click", event => {
    const point = event.detail ? scenePoint(event) : { x: 440, y: 204 };
    if (point) {
      disturb(point.x, Math.max(waterline + 9, Math.min(242, point.y)), 3.25);
      PondAudio.play("tap");
    }
  });
  document.addEventListener("skychange", event => {
    const time = performance.now() / 1000;
    if (mode !== document.documentElement.dataset.sky && event.detail?.fading && !motion.matches) {
      const cssTime = getComputedStyle(document.documentElement).getPropertyValue("--sky-fade").trim();
      const seconds = parseFloat(cssTime) / (cssTime.endsWith("ms") ? 1000 : 1);
      fade = { pixels: frame.data.slice(), started: time, duration: seconds > 0 ? seconds : 1.2 };
    }
    buildReflection();
    paint(motion.matches ? 0 : time);
  });
  motion.addEventListener("change", () => {
    surface.fill(0);
    previous.fill(0);
    pointer = null;
    lightStrength = 0;
    if (motion.matches) {
      fade = null;
      paint(0);
    }
  });

  buildReflection();
  paint(0);
  button.classList.remove("hidden");
  return { disturb, step };
})();
