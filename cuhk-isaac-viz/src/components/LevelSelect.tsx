import React, { useState, useEffect } from 'react';
import { PlayCircle, RotateCcw, RotateCw, Activity, Target, Circle, ArrowRightLeft, Volume2 } from 'lucide-react';
import { EXPERIMENTS } from '../experiments';
import xiaohuiLogo from './xiaohui.png';
import { isaacService } from '../services/isaacService';

interface LevelSelectProps {
  onSelectLevel: (levelId: string) => void;
  onBack: () => void;
}

const LevelSelect: React.FC<LevelSelectProps> = ({ onSelectLevel, onBack }) => {
  const [isAnimating, setIsAnimating] = useState(true);
  const [particles, setParticles] = useState<Array<{ x: number; y: number; delay: number; duration: number }>>([]);
  const [cardTilts, setCardTilts] = useState<{ [key: string]: { x: number; y: number } }>({});
  const [mousePositions, setMousePositions] = useState<{ [key: string]: { x: number; y: number } }>({});

  useEffect(() => {
    // 组件加载时触发动画
    setIsAnimating(true);
    const timer = setTimeout(() => setIsAnimating(false), 100);

    // 生成粒子位置
    const newParticles = Array.from({ length: 30 }, () => ({
      x: Math.random() * 100,
      y: Math.random() * 100,
      delay: Math.random() * 5,
      duration: 10 + Math.random() * 20
    }));
    setParticles(newParticles);

    // 初始化WebSocket连接并加载USD场景（只在首次进入时执行）
    const initializeConnection = async () => {
      console.log('📡 Initializing connection on LevelSelect...');

      // 检查是否已连接
      if (isaacService.isConnected()) {
        console.log('✅ Already connected, skipping initialization');
        return;
      }

      try {
        // 1. 连接WebSocket
        console.log('🔌 Connecting to Isaac Sim...');
        const connected = await isaacService.connect('level-select');

        if (connected) {
          console.log('✅ WebSocket connected');

          // 2. 加载exp.usd（统一的场景文件，默认加载实验1）
          console.log('📂 Loading USD scene...');
          const loaded = await isaacService.loadUSDScene('1');

          if (loaded) {
            console.log('✅ USD scene loaded, ready for experiment selection');
          } else {
            console.warn('⚠️ Failed to load USD scene');
          }
        } else {
          console.error('❌ Failed to connect to WebSocket');
        }
      } catch (error) {
        console.error('❌ Connection initialization error:', error);
      }
    };

    // 执行初始化
    initializeConnection();

    return () => {
      clearTimeout(timer);
      // 不断开连接，保持WebSocket在线
      console.log('🔄 LevelSelect unmounting, keeping connection alive');
    };
  }, []);
  // 根据实验类型返回对应的图标和主题色
  const getExperimentIcon = (id: string) => {
    switch(id) {
      case 'exp-01-angular-momentum': return { Icon: RotateCw, color: '#00f3ff', glow: 'cyan' };
      case 'exp-02-large-pendulum': return { Icon: Activity, color: '#ff00ff', glow: 'fuchsia' };
      case 'exp-03-ballistic-pendulum': return { Icon: Target, color: '#fbbf24', glow: 'amber' };
      case 'exp-04-driven-damped-oscillation': return { Icon: Activity, color: '#D4AF37', glow: 'yellow' };
      case 'exp-05-rotational-inertia': return { Icon: RotateCw, color: '#a855f7', glow: 'purple' };
      case 'exp-06-centripetal-force': return { Icon: Circle, color: '#fb923c', glow: 'orange' };
      case 'exp-07-momentum-conservation': return { Icon: ArrowRightLeft, color: '#10b981', glow: 'emerald' };
      case 'exp-08-resonance-air-column': return { Icon: Volume2, color: '#ec4899', glow: 'pink' };
      default: return { Icon: Activity, color: '#00f3ff', glow: 'cyan' };
    }
  };

  return (
    <div
      className={`min-h-screen bg-gradient-to-br from-gray-50 via-blue-50 to-purple-50 text-gray-900 p-6 md:p-12 relative transition-all duration-1000 ${
        isAnimating ? 'opacity-0 scale-95' : 'opacity-100 scale-100'
      }`}
      style={{ fontFamily: "'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif" }}
    >
      {/* Background Decor */}
      <div className="fixed top-0 right-0 w-[500px] h-[500px] bg-gradient-to-br from-blue-200/30 to-purple-200/30 rounded-full blur-[100px] pointer-events-none" />
      <div className="fixed bottom-0 left-0 w-[400px] h-[400px] bg-gradient-to-tr from-cyan-200/20 to-pink-200/20 rounded-full blur-[100px] pointer-events-none" />

      {/* 漂浮粒子背景 */}
      <div className="fixed inset-0 pointer-events-none overflow-hidden">
        {particles.map((particle, i) => (
          <div
            key={i}
            className="absolute rounded-full bg-blue-400/20 animate-float"
            style={{
              left: `${particle.x}%`,
              top: `${particle.y}%`,
              width: `${4 + Math.random() * 4}px`,
              height: `${4 + Math.random() * 4}px`,
              animationDelay: `${particle.delay}s`,
              animationDuration: `${particle.duration}s`
            }}
          />
        ))}
      </div>

      {/* 物理公式水印背景 */}
      <div className="fixed inset-0 pointer-events-none overflow-hidden opacity-[0.03] select-none">
        <div className="absolute top-[10%] left-[5%] text-6xl font-mono text-gray-900 rotate-12">F = ma</div>
        <div className="absolute top-[30%] right-[10%] text-5xl font-mono text-gray-900 -rotate-6">E = mc²</div>
        <div className="absolute bottom-[20%] left-[15%] text-4xl font-mono text-gray-900 rotate-6">v = ωr</div>
        <div className="absolute top-[60%] right-[20%] text-5xl font-mono text-gray-900 -rotate-12">F = -kx</div>
        <div className="absolute bottom-[40%] left-[40%] text-4xl font-mono text-gray-900 rotate-3">p = mv</div>
        <div className="absolute top-[45%] left-[60%] text-5xl font-mono text-gray-900 -rotate-6">L = Iω</div>
      </div>
      
      {/* Header */}
      <header
        className={`flex justify-between items-center mb-12 relative z-10 transition-all duration-700 delay-100 ${
          isAnimating ? 'opacity-0 -translate-y-10' : 'opacity-100 translate-y-0'
        }`}
      >
        <div className="flex items-center gap-6">
          <button onClick={onBack} className="p-3 border-2 border-gray-300 rounded-lg hover:bg-gray-200 hover:border-gray-400 transition-all group shadow-sm">
             <RotateCcw size={20} className="text-gray-700 group-hover:-rotate-180 transition-transform duration-500" />
          </button>
          <div>
            <h1 className="text-4xl font-black tracking-tighter text-transparent bg-clip-text bg-gradient-to-r from-gray-800 via-blue-600 to-purple-600">Menu</h1>
            
          </div>
        </div>
        <div className="text-right hidden md:block">
          <img
            src={xiaohuiLogo}
            alt="CUHK(SZ)"
            className="h-12 w-auto object-contain opacity-90 hover:opacity-100 transition-opacity duration-300"
          />
        </div>
      </header>

      {/* Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 relative z-10 pb-10">
        {EXPERIMENTS.map((level, index) => {
          const { Icon, color, glow } = getExperimentIcon(level.id);

          const tilt = cardTilts[level.id] || { x: 0, y: 0 };
          const mousePos = mousePositions[level.id] || { x: 0, y: 0 };

          return (
            <div
              key={level.id}
              onClick={() => !level.isLocked && onSelectLevel(level.id)}
              className={`
                group relative h-80 border-2 rounded-2xl overflow-hidden transition-all duration-300
                ${level.isLocked
                  ? 'border-gray-300 opacity-50 cursor-not-allowed bg-gray-100 grayscale'
                  : 'border-gray-200 bg-white/90 backdrop-blur-sm hover:border-gray-400 cursor-pointer hover:-translate-y-2 shadow-lg hover:shadow-2xl'
                }
                ${isAnimating ? 'opacity-0 translate-y-10' : 'opacity-100 translate-y-0'}
              `}
              style={{
                boxShadow: level.isLocked ? 'none' : `0 4px 20px rgba(0,0,0,0.08)`,
                transition: `all 0.5s cubic-bezier(0.4, 0, 0.2, 1) ${index * 0.1}s`,
                transform: `perspective(1000px) rotateX(${tilt.x}deg) rotateY(${tilt.y}deg) ${isAnimating ? 'translateY(40px)' : 'translateY(0)'}`,
                transformStyle: 'preserve-3d'
              }}
              onMouseMove={(e) => {
                if (!level.isLocked) {
                  const rect = e.currentTarget.getBoundingClientRect();
                  const x = (e.clientY - rect.top - rect.height / 2) / 15;
                  const y = -(e.clientX - rect.left - rect.width / 2) / 15;
                  setCardTilts(prev => ({ ...prev, [level.id]: { x, y } }));

                  const mouseX = e.clientX - rect.left;
                  const mouseY = e.clientY - rect.top;
                  setMousePositions(prev => ({ ...prev, [level.id]: { x: mouseX, y: mouseY } }));
                }
              }}
              onMouseEnter={(e) => {
                if (!level.isLocked) {
                  e.currentTarget.style.boxShadow = `0 20px 60px ${color}30, 0 0 40px ${color}20`;
                  e.currentTarget.style.borderColor = color;
                }
              }}
              onMouseLeave={(e) => {
                if (!level.isLocked) {
                  e.currentTarget.style.boxShadow = `0 4px 20px rgba(0,0,0,0.08)`;
                  e.currentTarget.style.borderColor = '#e5e7eb';
                  setCardTilts(prev => ({ ...prev, [level.id]: { x: 0, y: 0 } }));
                }
              }}
            >
              {/* 鼠标跟随光斑 */}
              <div
                className="absolute inset-0 opacity-0 group-hover:opacity-100 transition-opacity duration-300 pointer-events-none"
                style={{
                  background: `radial-gradient(circle 200px at ${mousePos.x}px ${mousePos.y}px, ${color}25, transparent 70%)`
                }}
              />

              {/* 背景图片层 */}
              <div className="absolute inset-0 opacity-25">
                <img
                  src={level.thumbnail}
                  alt={level.title}
                  className="w-full h-full object-cover group-hover:scale-110 group-hover:opacity-35 transition-all duration-700"
                />
                <div className="absolute inset-0 bg-gradient-to-br from-white/95 via-white/90 to-gray-50/95" />
              </div>

              {/* 扫描线效果 */}
              <div className="absolute inset-0 opacity-0 group-hover:opacity-100 transition-opacity duration-500">
                <div className="absolute inset-0 bg-gradient-to-b from-transparent via-blue-400/15 to-transparent h-20 animate-scan" />
              </div>

              {/* 网格背景 */}
              <div className="absolute inset-0 opacity-5 group-hover:opacity-10 transition-opacity duration-500"
                   style={{
                     backgroundImage: 'linear-gradient(rgba(0,0,0,0.05) 1px, transparent 1px), linear-gradient(90deg, rgba(0,0,0,0.05) 1px, transparent 1px)',
                     backgroundSize: '20px 20px'
                   }} />

              {/* 顶部图标区域 */}
              <div className="absolute top-0 left-0 right-0 p-5 z-20">
                <div className="flex items-start justify-between">
                  {/* 主图标 */}
                  <div className="relative">
                    <div
                      className="absolute inset-0 blur-xl opacity-40 group-hover:opacity-70 transition-opacity duration-500"
                      style={{ backgroundColor: color }}
                    />
                    <div
                      className="relative p-3 rounded-xl border-2 bg-white/90 backdrop-blur-sm group-hover:scale-110 group-hover:rotate-12 transition-all duration-500 shadow-md"
                      style={{ borderColor: `${color}80` }}
                    >
                      <Icon size={32} style={{ color }} />
                    </div>
                    {/* 脉冲圆环 */}
                    <div
                      className="absolute inset-0 rounded-xl border-2 opacity-0 group-hover:opacity-100 group-hover:scale-150 transition-all duration-700"
                      style={{ borderColor: color }}
                    />
                  </div>

                  {/* 难度徽章 */}
                  <div className="flex flex-col items-end gap-2">
                    <span className={`text-[10px] font-mono px-2 py-1 rounded-lg border backdrop-blur-sm font-semibold shadow-sm ${
                      level.difficulty === 'Easy' ? 'border-green-600/50 text-green-700 bg-green-100' :
                      level.difficulty === 'Medium' ? 'border-yellow-600/50 text-yellow-700 bg-yellow-100' :
                      'border-red-600/50 text-red-700 bg-red-100'
                    }`}>
                      {level.difficulty}
                    </span>
                    <span className="font-mono text-gray-600 text-[10px] tracking-wider font-medium">EXP_0{index + 1}</span>
                  </div>
                </div>
              </div>

              {/* 数据流动效果 */}
              <div className="absolute top-24 left-5 right-5 opacity-0 group-hover:opacity-100 transition-all duration-500 z-10">
                <div className="flex gap-1">
                  {[...Array(12)].map((_, i) => (
                    <div
                      key={i}
                      className="w-1 rounded-full animate-pulse"
                      style={{
                        height: `${Math.random() * 20 + 10}px`,
                        backgroundColor: color,
                        animationDelay: `${i * 0.1}s`,
                        opacity: 0.6
                      }}
                    />
                  ))}
                </div>
              </div>

              {/* 内容区域 */}
              <div className="absolute inset-0 p-5 flex flex-col justify-end z-20">
                <div className="space-y-2">
                  {/* 标题 */}
                  <h3
                    className="text-xl font-black leading-tight transition-all duration-300 group-hover:translate-x-1 text-gray-800"
                    style={{
                      textShadow: level.isLocked ? 'none' : `0 0 15px ${color}40`
                    }}
                  >
                    {level.title}
                  </h3>

                  {/* 描述 */}
                  <p className="text-gray-600 text-xs leading-relaxed line-clamp-2 group-hover:text-gray-700 transition-colors font-medium">
                    {level.description}
                  </p>

                  {/* 底部状态栏 */}
                  <div className="flex items-center justify-between pt-3 mt-2 border-t border-gray-300/60">
                    <div className="flex items-center gap-2">
                      <div
                        className="w-2 h-2 rounded-full animate-pulse shadow-sm"
                        style={{ backgroundColor: level.isLocked ? '#999' : color }}
                      />
                      <span className="text-[10px] font-mono text-gray-700 font-semibold">
                        {level.isLocked ? 'LOCKED' : 'READY'}
                      </span>
                    </div>

                    {!level.isLocked && (
                      <PlayCircle
                        className="opacity-0 group-hover:opacity-100 translate-x-4 group-hover:translate-x-0 transition-all duration-300"
                        size={20}
                        style={{ color }}
                      />
                    )}
                  </div>
                </div>
              </div>

              {/* 底部光效 */}
              <div
                className="absolute bottom-0 left-0 right-0 h-1 transform scale-x-0 group-hover:scale-x-100 transition-transform duration-700 origin-left"
                style={{
                  background: `linear-gradient(90deg, transparent, ${color}, transparent)`
                }}
              />

              {/* 边框流光效果 */}
              <div
                className="absolute inset-0 opacity-0 group-hover:opacity-100 transition-opacity duration-500 pointer-events-none"
                style={{
                  background: `linear-gradient(90deg, transparent 0%, ${color}20 50%, transparent 100%)`,
                  animation: 'shimmer 2s infinite',
                  transform: 'translateX(-100%)'
                }}
              />
            </div>
          );
        })}
      </div>

      {/* CSS 动画 */}
      <style>{`
        @keyframes scan {
          0% { transform: translateY(-100%); }
          100% { transform: translateY(400%); }
        }

        @keyframes shimmer {
          0% { transform: translateX(-100%); }
          100% { transform: translateX(200%); }
        }

        @keyframes float {
          0%, 100% {
            transform: translateY(0) translateX(0) rotate(0deg);
            opacity: 0.2;
          }
          25% {
            transform: translateY(-30px) translateX(15px) rotate(90deg);
            opacity: 0.5;
          }
          50% {
            transform: translateY(-60px) translateX(-15px) rotate(180deg);
            opacity: 0.8;
          }
          75% {
            transform: translateY(-30px) translateX(10px) rotate(270deg);
            opacity: 0.5;
          }
        }

        .animate-float {
          animation: float linear infinite;
        }
      `}</style>
    </div>
  );
};

export default LevelSelect;