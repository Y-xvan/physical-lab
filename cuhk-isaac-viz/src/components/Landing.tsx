import React, { useEffect, useState, useRef } from 'react';
import { ChevronRight } from 'lucide-react';

interface LandingProps {
  onEnter: () => void;
}

// 物理粒子接口
interface Particle {
  id: number;
  x: number;
  y: number;
  vx: number;
  vy: number;
  size: number;
  color: string;
  opacity: number;
  mass: number;
}

// 物理公式接口
interface PhysicsFormula {
  id: number;
  text: string;
  x: number;
  y: number;
  vx: number;
  vy: number;
  rotation: number;
  rotationSpeed: number;
  scale: number;
  opacity: number;
}

// 波纹效果接口
interface Ripple {
  id: number;
  x: number;
  y: number;
  timestamp: number;
}

const Landing: React.FC<LandingProps> = ({ onEnter }) => {
  const [mounted, setMounted] = useState(false);
  const [glitchActive, setGlitchActive] = useState(false);
  const starsContainerRef = useRef<HTMLDivElement>(null);
  const particlesRef = useRef<Particle[]>([]);
  const formulasRef = useRef<PhysicsFormula[]>([]);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const rippleCanvasRef = useRef<HTMLCanvasElement>(null);
  const [ripples, setRipples] = useState<Ripple[]>([]);

  // 生成随机星星数据（只生成一次）
  const [stars] = useState(() =>
    Array.from({ length: 80 }, (_, i) => ({
      id: i,
      x: Math.random() * 100,
      y: Math.random() * 100,
      size: 3 + Math.random() * 8,
      depth: Math.random(),
      color: [
        '#00f3ff', '#ffffff', '#a855f7', '#60a5fa',
        '#ec4899', '#f59e0b', '#10b981', '#8b5cf6',
      ][Math.floor(Math.random() * 8)],
      opacity: 0.3 + Math.random() * 0.7,
    }))
  );

  // 物理公式列表
  const physicsFormulas = [
    'E=mc²', 'F=ma', 'p=mv', 'W=Fd',
    'v=at', 'K=½mv²', 'U=mgh', 'P=E/t',
    '∫', '∑', 'Δ', 'α', 'β', 'γ', 'θ', 'ω',
    'λ', 'μ', 'σ', 'π', '∇', '∂', 'ℏ', '∞'
  ];

  useEffect(() => {
    setMounted(true);

    // 初始化粒子系统 - 均匀分布
    const initParticles = () => {
      const colors = ['#00f3ff', '#a855f7', '#60a5fa', '#ec4899', '#f59e0b', '#10b981'];
      const cols = 10;
      const rows = 5;
      const cellWidth = window.innerWidth / cols;
      const cellHeight = window.innerHeight / rows;

      particlesRef.current = Array.from({ length: 50 }, (_, i) => {
        // 在网格内随机分布
        const col = i % cols;
        const row = Math.floor(i / cols);
        const x = col * cellWidth + Math.random() * cellWidth;
        const y = row * cellHeight + Math.random() * cellHeight;

        return {
          id: i,
          x,
          y,
          vx: (Math.random() - 0.5) * 0.8,
          vy: (Math.random() - 0.5) * 0.8,
          size: 2 + Math.random() * 3, // 小粒子（2-5px）
          color: colors[Math.floor(Math.random() * colors.length)],
          opacity: 0.5 + Math.random() * 0.4,
          mass: 1 + Math.random() * 2,
        };
      });
    };

    // 初始化物理公式 - 均匀分布
    const initFormulas = () => {
      const cols = 5;
      const rows = 4;
      const cellWidth = window.innerWidth / cols;
      const cellHeight = window.innerHeight / rows;

      formulasRef.current = Array.from({ length: 20 }, (_, i) => {
        // 在网格内随机分布
        const col = i % cols;
        const row = Math.floor(i / cols);
        const x = col * cellWidth + Math.random() * cellWidth;
        const y = row * cellHeight + Math.random() * cellHeight;

        return {
          id: i,
          text: physicsFormulas[Math.floor(Math.random() * physicsFormulas.length)],
          x,
          y,
          vx: (Math.random() - 0.5) * 0.3,
          vy: (Math.random() - 0.5) * 0.3,
          rotation: Math.random() * 360,
          rotationSpeed: (Math.random() - 0.5) * 0.5,
          scale: 0.5 + Math.random() * 0.5, // 小公式（0.5-1.0）
          opacity: 0.15 + Math.random() * 0.25, // 透明度（0.15-0.4）
        };
      });
    };

    initParticles();
    initFormulas();

    // 随机触发故障效果
    const glitchInterval = setInterval(() => {
      setGlitchActive(true);
      setTimeout(() => setGlitchActive(false), 200);
    }, 5000);

    // 鼠标位置和交互
    let rafId: number | null = null;
    const mousePos = { x: 0, y: 0, clientX: 0, clientY: 0 };
    let isMouseDown = false;

    // 更新星星位置（视差效果）
    const updateStarPositions = () => {
      if (!starsContainerRef.current) return;
      const starElements = starsContainerRef.current.children;

      for (let i = 0; i < starElements.length; i++) {
        const star = starElements[i] as HTMLElement;
        const depth = parseFloat(star.dataset.depth || '0');
        const parallaxX = mousePos.x * depth * 120;
        const parallaxY = mousePos.y * depth * 120;
        const rotation = i * 45;
        star.style.transform = `translate3d(${parallaxX}px, ${parallaxY}px, 0) rotate(${rotation}deg)`;
      }
    };

    // 粒子物理更新
    const updateParticles = () => {
      const canvas = canvasRef.current;
      if (!canvas) return;

      const ctx = canvas.getContext('2d');
      if (!ctx) return;

      // 清除画布
      ctx.clearRect(0, 0, canvas.width, canvas.height);

      particlesRef.current.forEach((particle) => {
        // 引力/斥力效果 - 增强版
        const dx = mousePos.clientX - particle.x;
        const dy = mousePos.clientY - particle.y;
        const distance = Math.sqrt(dx * dx + dy * dy);

        if (distance < 300 && distance > 0) {
          const force = isMouseDown ? -150 : 80; // 增强力度：按下排斥（-150），否则吸引（80）
          const angle = Math.atan2(dy, dx);
          const strength = (force / (distance * 0.5)) * particle.mass;
          particle.vx += Math.cos(angle) * strength * 0.02;
          particle.vy += Math.sin(angle) * strength * 0.02;
        }

        // 轻微向上浮动（模拟浮力）
        particle.vy -= 0.01;

        // 摩擦力（降低阻力，让运动更流畅）
        particle.vx *= 0.99;
        particle.vy *= 0.99;

        // 更新位置
        particle.x += particle.vx;
        particle.y += particle.vy;

        // 边界反弹
        if (particle.x < 0 || particle.x > canvas.width) {
          particle.vx *= -0.8;
          particle.x = Math.max(0, Math.min(canvas.width, particle.x));
        }
        if (particle.y < 0 || particle.y > canvas.height) {
          particle.vy *= -0.8;
          particle.y = Math.max(0, Math.min(canvas.height, particle.y));
        }

        // 绘制粒子 - 增强辉光
        ctx.save();

        // 外层大光晕
        ctx.beginPath();
        ctx.arc(particle.x, particle.y, particle.size * 3, 0, Math.PI * 2);
        const gradient = ctx.createRadialGradient(
          particle.x, particle.y, 0,
          particle.x, particle.y, particle.size * 3
        );
        gradient.addColorStop(0, particle.color + '40');
        gradient.addColorStop(1, particle.color + '00');
        ctx.fillStyle = gradient;
        ctx.fill();

        // 主粒子
        ctx.beginPath();
        ctx.arc(particle.x, particle.y, particle.size, 0, Math.PI * 2);
        ctx.fillStyle = particle.color;
        ctx.globalAlpha = particle.opacity;
        ctx.shadowBlur = 25;
        ctx.shadowColor = particle.color;
        ctx.fill();

        // 内核高亮
        ctx.beginPath();
        ctx.arc(particle.x, particle.y, particle.size * 0.5, 0, Math.PI * 2);
        ctx.fillStyle = '#ffffff';
        ctx.globalAlpha = 0.8;
        ctx.shadowBlur = 15;
        ctx.fill();

        ctx.restore();

        // 粒子间连线 - 更明显
        particlesRef.current.forEach((other) => {
          if (particle.id >= other.id) return;
          const dx = other.x - particle.x;
          const dy = other.y - particle.y;
          const dist = Math.sqrt(dx * dx + dy * dy);

          if (dist < 150) {
            ctx.beginPath();
            ctx.moveTo(particle.x, particle.y);
            ctx.lineTo(other.x, other.y);

            const lineGradient = ctx.createLinearGradient(
              particle.x, particle.y,
              other.x, other.y
            );
            lineGradient.addColorStop(0, particle.color);
            lineGradient.addColorStop(1, other.color);
            ctx.strokeStyle = lineGradient;
            ctx.globalAlpha = (1 - dist / 150) * 0.4;
            ctx.lineWidth = 1.5;
            ctx.shadowBlur = 5;
            ctx.shadowColor = particle.color;
            ctx.stroke();
          }
        });
      });
    };

    // 物理公式动画更新
    const updateFormulas = () => {
      const canvas = canvasRef.current;
      if (!canvas) return;

      const ctx = canvas.getContext('2d');
      if (!ctx) return;

      formulasRef.current.forEach((formula) => {
        // 更新位置
        formula.x += formula.vx;
        formula.y += formula.vy;
        formula.rotation += formula.rotationSpeed;

        // 边界环绕
        if (formula.x < -100) formula.x = canvas.width + 100;
        if (formula.x > canvas.width + 100) formula.x = -100;
        if (formula.y < -100) formula.y = canvas.height + 100;
        if (formula.y > canvas.height + 100) formula.y = -100;

        // 绘制公式 - 小尺寸版
        ctx.save();
        ctx.translate(formula.x, formula.y);
        ctx.rotate((formula.rotation * Math.PI) / 180);
        ctx.scale(formula.scale, formula.scale);

        ctx.font = 'bold 20px "Times New Roman", serif'; // 更小的字体
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';

        // 外层辉光
        ctx.shadowBlur = 15;
        ctx.shadowColor = '#00f3ff';
        ctx.strokeStyle = '#00f3ff';
        ctx.lineWidth = 1.5;
        ctx.globalAlpha = formula.opacity * 0.5;
        ctx.strokeText(formula.text, 0, 0);

        // 主文字
        ctx.shadowBlur = 12;
        ctx.fillStyle = '#00f3ff';
        ctx.globalAlpha = formula.opacity;
        ctx.fillText(formula.text, 0, 0);

        // 高亮描边
        ctx.strokeStyle = '#ffffff';
        ctx.lineWidth = 0.3;
        ctx.globalAlpha = formula.opacity * 0.6;
        ctx.strokeText(formula.text, 0, 0);

        ctx.shadowBlur = 0;
        ctx.globalAlpha = 1;
        ctx.restore();
      });
    };

    // 波纹动画 - 增强版
    const updateRipples = () => {
      const canvas = rippleCanvasRef.current;
      if (!canvas) return;

      const ctx = canvas.getContext('2d');
      if (!ctx) return;

      ctx.clearRect(0, 0, canvas.width, canvas.height);

      const now = Date.now();
      setRipples((prev) => {
        const active = prev.filter((ripple) => now - ripple.timestamp < 2500);

        active.forEach((ripple) => {
          const age = now - ripple.timestamp;
          const maxRadius = 400;
          const radius = (age / 2500) * maxRadius;
          const opacity = 1 - age / 2500;

          // 外层波纹（青色）
          ctx.beginPath();
          ctx.arc(ripple.x, ripple.y, radius, 0, Math.PI * 2);
          ctx.strokeStyle = '#00f3ff';
          ctx.globalAlpha = opacity * 0.8;
          ctx.lineWidth = 3;
          ctx.shadowBlur = 15;
          ctx.shadowColor = '#00f3ff';
          ctx.stroke();

          // 中层波纹（紫色）
          ctx.beginPath();
          ctx.arc(ripple.x, ripple.y, radius * 0.75, 0, Math.PI * 2);
          ctx.strokeStyle = '#a855f7';
          ctx.globalAlpha = opacity * 0.6;
          ctx.lineWidth = 2.5;
          ctx.shadowBlur = 12;
          ctx.shadowColor = '#a855f7';
          ctx.stroke();

          // 内层波纹（蓝色）
          ctx.beginPath();
          ctx.arc(ripple.x, ripple.y, radius * 0.5, 0, Math.PI * 2);
          ctx.strokeStyle = '#60a5fa';
          ctx.globalAlpha = opacity * 0.4;
          ctx.lineWidth = 2;
          ctx.shadowBlur = 10;
          ctx.shadowColor = '#60a5fa';
          ctx.stroke();

          // 中心爆炸光点
          if (age < 500) {
            const centerOpacity = 1 - age / 500;
            ctx.beginPath();
            ctx.arc(ripple.x, ripple.y, 5, 0, Math.PI * 2);
            ctx.fillStyle = '#ffffff';
            ctx.globalAlpha = centerOpacity;
            ctx.shadowBlur = 20;
            ctx.shadowColor = '#00f3ff';
            ctx.fill();
          }

          ctx.shadowBlur = 0;
          ctx.globalAlpha = 1;
        });

        return active;
      });
    };

    // 动画循环
    const animate = () => {
      updateStarPositions();
      updateParticles();
      updateFormulas();
      updateRipples();
      rafId = requestAnimationFrame(animate);
    };

    // 鼠标移动
    const handleMouseMove = (e: MouseEvent) => {
      mousePos.x = (e.clientX / window.innerWidth - 0.5) * 2;
      mousePos.y = (e.clientY / window.innerHeight - 0.5) * 2;
      mousePos.clientX = e.clientX;
      mousePos.clientY = e.clientY;
    };

    // 鼠标按下/释放
    const handleMouseDown = () => { isMouseDown = true; };
    const handleMouseUp = () => { isMouseDown = false; };

    // 点击产生波纹
    const handleClick = (e: MouseEvent) => {
      setRipples((prev) => [
        ...prev,
        { id: Date.now(), x: e.clientX, y: e.clientY, timestamp: Date.now() },
      ]);
    };

    // Canvas 大小调整
    const resizeCanvas = () => {
      if (canvasRef.current) {
        canvasRef.current.width = window.innerWidth;
        canvasRef.current.height = window.innerHeight;
      }
      if (rippleCanvasRef.current) {
        rippleCanvasRef.current.width = window.innerWidth;
        rippleCanvasRef.current.height = window.innerHeight;
      }
    };

    resizeCanvas();
    animate();

    window.addEventListener('mousemove', handleMouseMove);
    window.addEventListener('mousedown', handleMouseDown);
    window.addEventListener('mouseup', handleMouseUp);
    window.addEventListener('click', handleClick);
    window.addEventListener('resize', resizeCanvas);

    return () => {
      clearInterval(glitchInterval);
      window.removeEventListener('mousemove', handleMouseMove);
      window.removeEventListener('mousedown', handleMouseDown);
      window.removeEventListener('mouseup', handleMouseUp);
      window.removeEventListener('click', handleClick);
      window.removeEventListener('resize', resizeCanvas);
      if (rafId !== null) {
        cancelAnimationFrame(rafId);
      }
    };
  }, []);

  return (
    <div className="relative w-full h-screen overflow-hidden bg-black flex flex-col items-center justify-center">
      {/* 交互式星系背景 */}
      <div className="absolute inset-0 z-0">
        {/* 径向渐变背景 */}
        <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_center,rgba(20,20,40,1)_0%,black_100%)]" />

        {/* 交互式星星 - 使用ref直接操作DOM，避免重渲染 */}
        <div ref={starsContainerRef} className="absolute inset-0">
          {stars.map((star) => (
            <div
              key={star.id}
              data-depth={star.depth}
              className="absolute will-change-transform"
              style={{
                left: `${star.x}%`,
                top: `${star.y}%`,
                width: `${star.size}px`,
                height: `${star.size}px`,
                backgroundColor: star.color,
                opacity: star.opacity,
                transform: `translate3d(0, 0, 0) rotate(${star.id * 45}deg)`,
                boxShadow: `0 0 ${star.size * 2}px ${star.color}`,
                filter: star.depth > 0.7 ? 'blur(0.5px)' : 'none',
                transition: 'transform 0.1s ease-out',
              }}
            />
          ))}
        </div>

        {/* 物理粒子系统和公式 Canvas */}
        <canvas
          ref={canvasRef}
          className="absolute inset-0 pointer-events-none"
          style={{ zIndex: 5, mixBlendMode: 'screen' }}
        />

        {/* 波纹效果 Canvas */}
        <canvas
          ref={rippleCanvasRef}
          className="absolute inset-0 pointer-events-none"
          style={{ zIndex: 15, mixBlendMode: 'screen' }}
        />

        {/* 光晕效果 */}
        <div className="absolute bottom-0 left-0 right-0 h-96 bg-gradient-to-t from-purple-900/10 via-blue-900/5 to-transparent pointer-events-none" />
        <div className="absolute top-0 left-0 right-0 h-96 bg-gradient-to-b from-cyan-900/5 to-transparent pointer-events-none" />

        {/* 能量脉冲环 */}
        <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 pointer-events-none">
          <div className="w-96 h-96 rounded-full border-2 border-cyan-500/20 animate-ping" style={{ animationDuration: '3s' }} />
          <div className="absolute inset-0 w-96 h-96 rounded-full border border-purple-500/10 animate-pulse" style={{ animationDuration: '4s' }} />
        </div>
      </div>

      {/* 主内容 */}
      <div className={`z-20 flex flex-col items-center text-center transition-all duration-1000 transform mt-24 ${mounted ? 'translate-y-0 opacity-100' : 'translate-y-10 opacity-0'}`}>

        {/* 标题 - 故障效果 */}
        <div className="relative mb-4">
          <h1 className={`text-2xl md:text-4xl font-black tracking-wider mb-2 ${glitchActive ? 'glitch' : ''}`}>
            <span className="text-transparent bg-clip-text bg-gradient-to-r from-cyan-300 via-white to-cyan-300 font-cinzel neon-glow neon-pulse">
              探索物理世界
            </span>
          </h1>

          {/* 下划线动画 */}
          <div className="h-1 w-0 group-hover:w-full bg-gradient-to-r from-cyan-500 to-purple-500 transition-all duration-1000 mx-auto" />
        </div>

        {/* 副标题 */}
        <div className="mb-6 relative">
          <h2 className="text-lg md:text-xl font-poiret font-normal tracking-[0.2em]" style={{
            textShadow: '0 0 20px rgba(0, 243, 255, 0.5), 0 4px 8px rgba(0, 0, 0, 0.8)'
          }}>
            <span className="text-transparent bg-clip-text bg-gradient-to-r from-cyan-400 via-blue-300 to-purple-400">
              万物之理 虚实之间
            </span>
          </h2>

          {/* 数据流动效果 */}
          <div className="absolute -bottom-4 left-0 right-0 flex justify-center gap-1 opacity-30">
            {[...Array(8)].map((_, i) => (
              <div key={i} className="w-1 h-1 bg-cyan-400 rounded-full animate-pulse"
                   style={{ animationDelay: `${i * 0.1}s` }} />
            ))}
          </div>
        </div>

        

        {/* CTA按钮 - 超酷版 */}
        <button
          onClick={onEnter}
          className="group relative px-10 py-4 bg-transparent overflow-hidden mb-20 z-30"
        >
          {/* 边框动画 */}
          <div className="absolute inset-0 border-2 border-cyan-500/50 group-hover:border-cyan-400 transition-colors" />
          <div className="absolute inset-0 border-2 border-purple-500/30 animate-pulse" style={{ clipPath: 'polygon(0 0, 50% 0, 50% 100%, 0 100%)' }} />

          {/* 背景光效 */}
          <div className="absolute inset-0 bg-gradient-to-r from-cyan-500/0 via-cyan-500/20 to-cyan-500/0 -translate-x-full group-hover:translate-x-full transition-transform duration-1000" />

          {/* 粒子爆发效果 */}
          <div className="absolute inset-0 opacity-0 group-hover:opacity-100 transition-opacity">
            {[...Array(6)].map((_, i) => (
              <div
                key={i}
                className="absolute w-1 h-1 bg-cyan-400 rounded-full animate-ping"
                style={{
                  top: '50%',
                  left: '50%',
                  animationDelay: `${i * 0.1}s`,
                  animationDuration: '1s',
                }}
              />
            ))}
          </div>

          {/* 按钮内容 */}
          <span className="relative flex items-center gap-2 text-sm font-semibold font-philosopher tracking-widest">
            <span className="text-transparent bg-clip-text bg-gradient-to-r from-cyan-400 to-white group-hover:from-white group-hover:to-cyan-400 transition-all">
              INITIALIZE LINK
            </span>
            <ChevronRight className="text-cyan-400 group-hover:translate-x-2 transition-transform" size={16} />
          </span>

          {/* 底部光带 */}
          <div className="absolute bottom-0 left-0 right-0 h-0.5 bg-gradient-to-r from-transparent via-cyan-500 to-transparent scale-x-0 group-hover:scale-x-100 transition-transform duration-500" />
        </button>
      </div>

      {/* 底部装饰 - 增强版 */}
      <div className="absolute bottom-0 left-0 right-0 pb-6 z-20">
        {/* 物理常数装饰 */}
        <div className="flex justify-center gap-8 mb-3 text-[10px] text-cyan-400/40 font-mono">
          <span className="animate-pulse" style={{ animationDelay: '0s', animationDuration: '3s' }}>c = 3×10⁸ m/s</span>
          <span className="animate-pulse" style={{ animationDelay: '0.5s', animationDuration: '3s' }}>G = 6.67×10⁻¹¹</span>
          <span className="animate-pulse" style={{ animationDelay: '1s', animationDuration: '3s' }}>h = 6.626×10⁻³⁴</span>
        </div>

        {/* 标语 */}
        <div className="flex justify-center mb-2">
          <span className="text-xs font-rajdhani font-semibold tracking-wider" style={{
            textShadow: '0 0 15px rgba(0, 243, 255, 0.4), 0 2px 4px rgba(0, 0, 0, 0.6)'
          }}>
            <span className="text-transparent bg-clip-text bg-gradient-to-r from-cyan-400 via-blue-400 to-purple-400">
              重新定义物理实验
            </span>
          </span>
        </div>

        {/* 进度条装饰 */}
        <div className="w-48 h-0.5 bg-gray-800 mx-auto rounded-full overflow-hidden">
          <div className="h-full bg-gradient-to-r from-cyan-500 to-purple-500 animate-progress" />
        </div>
      </div>

    </div>
  );
};

export default Landing;
