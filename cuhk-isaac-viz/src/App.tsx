import React, { useState, useEffect } from 'react';
import Landing from './components/Landing';
import LevelSelect from './components/LevelSelect';
import ExperimentView from './components/ExperimentView';
import { EXPERIMENTS } from './experiments'; // 导入配置
import { isaacService } from './services/isaacService';

enum AppState {
  LANDING,
  LEVEL_SELECT,
  EXPERIMENT_VIEW
}

const App: React.FC = () => {
  const [currentState, setCurrentState] = useState<AppState>(AppState.LANDING);
  const [selectedExperimentId, setSelectedExperimentId] = useState<string | null>(null);

  // 全局清理：只在应用完全卸载时断开WebSocket
  useEffect(() => {
    console.log('🚀 App mounted');

    return () => {
      console.log('🛑 App unmounting, disconnecting WebSocket');
      isaacService.disconnect(true);  // 强制断开连接
    };
  }, []);

  const handleEnterLab = () => {
    setCurrentState(AppState.LEVEL_SELECT);
  };

  const handleSelectLevel = (levelId: string) => {
    setSelectedExperimentId(levelId);
    setCurrentState(AppState.EXPERIMENT_VIEW);
  };

  const handleBackToLevels = () => {
    setCurrentState(AppState.LEVEL_SELECT);
    setSelectedExperimentId(null);
  };

  const handleBackToLanding = () => {
    setCurrentState(AppState.LANDING);
  };

  // 查找当前选中的配置
  const selectedConfig = EXPERIMENTS.find(e => e.id === selectedExperimentId);

  return (
    <div className={`antialiased text-slate-900 bg-black h-screen w-screen ${
      currentState === AppState.LEVEL_SELECT ? 'overflow-auto' : 'overflow-hidden'
    }`}>
      {currentState === AppState.LANDING && (
        <Landing onEnter={handleEnterLab} />
      )}

      {currentState === AppState.LEVEL_SELECT && (
        <LevelSelect
          onSelectLevel={handleSelectLevel}
          onBack={handleBackToLanding}
        />
      )}

      {/* 传递配置给 ExperimentView */}
      {currentState === AppState.EXPERIMENT_VIEW && selectedConfig && (
        <ExperimentView config={selectedConfig} onBack={handleBackToLevels} />
      )}
    </div>
  );
};

export default App;