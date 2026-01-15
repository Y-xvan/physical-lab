import { type ExperimentConfig } from './types';

export const EXPERIMENTS: ExperimentConfig[] = [
  {
    id: 'exp-01-angular-momentum',
    title: 'Conservation of Angular Momentum',
    description: 'Study the conservation of angular momentum in rotating systems.',
    thumbnail: 'https://picsum.photos/seed/angular-momentum/400/225',
    usdPath: '/home/zhiren/Isaaclab_Assets/Experiment/exp.usd',
    experimentNumber: '1',
    difficulty: 'Easy',
    isLocked: false,
    controls: [
      { id: 'disk_mass', label: 'Disk (Lower) Mass (kg)', type: 'slider', min: 0.1, max: 5, step: 0.1, defaultValue: 1.0, command: 'set_disk_mass' },
      { id: 'ring_mass', label: 'Disk (Upper) Mass (kg)', type: 'slider', min: 0.1, max: 5, step: 0.1, defaultValue: 1.0, command: 'set_ring_mass' },
      { id: 'initial_velocity', label: 'Initial Angular Velocity (rad/s)', type: 'slider', min: 0, max: 10, step: 0.5, defaultValue: 5.0, command: 'set_initial_velocity' },
      { id: 'run', label: 'Run', type: 'button', command: 'start_simulation' },
      { id: 'reset', label: 'Reset', type: 'button', command: 'reset_env' }
    ],
    chartConfig: [
      { key: 'disk_angular_velocity', color: '#00f3ff', label: 'Disk (Lower) ω (rad/s)', yAxisId: 'left' },
      { key: 'ring_angular_velocity', color: '#10b981', label: 'Disk (Upper) ω (rad/s)', yAxisId: 'left' }
    ]
  },
  {
    id: 'exp-02-large-pendulum',
    title: 'Large Amplitude Pendulum',
    description: 'Investigate pendulum motion at large angles beyond small-angle approximation.',
    thumbnail: 'https://picsum.photos/seed/pendulum/400/225',
    usdPath: '/home/zhiren/Isaaclab_Assets/Experiment/exp.usd',
    experimentNumber: '2',
    difficulty: 'Easy',
    isLocked: false,
    controls: [
      { id: 'initial_angle', label: 'Initial Angle (°)', type: 'slider', min: 10, max: 170, step: 5, defaultValue: 90, command: 'set_initial_angle' },
      { id: 'mass1', label: 'Cylinder_01 Mass (kg)', type: 'slider', min: 0.1, max: 5, step: 0.1, defaultValue: 1.0, command: 'set_exp2_mass1' },
      { id: 'mass2', label: 'Cylinder_02 Mass (kg)', type: 'slider', min: 0.1, max: 5, step: 0.1, defaultValue: 1.0, command: 'set_exp2_mass2' },
      { id: 'run', label: 'Run', type: 'button', command: 'start_simulation' },
      { id: 'reset', label: 'Reset', type: 'button', command: 'reset_env' }
    ],
    chartConfig: [
      { key: 'angle', color: '#ff00ff', label: 'Angle (°)', yAxisId: 'left' }
    ],
    // 额外的数值显示（不在图表中，但在顶部显示）
    extraMetrics: [
      { key: 'period', label: 'Period (s)', color: '#00ff00' }
    ]
  },
  {
    id: 'exp-03-ballistic-pendulum',
    title: 'Conservation of Energy (Ballistic Pendulum)',
    description: 'Measure projectile velocity through energy conservation in ballistic pendulum.',
    thumbnail: 'https://picsum.photos/seed/ballistic/400/225',
    usdPath: '/home/zhiren/Isaaclab_Assets/Experiment/exp.usd',
    experimentNumber: '3',
    difficulty: 'Medium',
    isLocked: false,
    controls: [
      { id: 'projectile_mass', label: 'Projectile Mass (kg)', type: 'slider', min: 0.01, max: 0.5, step: 0.01, defaultValue: 0.05, command: 'set_projectile_mass' },
      { id: 'pendulum_mass', label: 'Pendulum Mass (kg)', type: 'slider', min: 0.5, max: 5, step: 0.1, defaultValue: 2.0, command: 'set_pendulum_mass' },
      { id: 'run', label: 'Fire', type: 'button', command: 'start_simulation' },
      { id: 'reset', label: 'Reset', type: 'button', command: 'reset' }
    ],
    chartConfig: [
      { key: 'velocity', color: '#00f3ff', label: 'Velocity (m/s)', yAxisId: 'left' },
      { key: 'energy', color: '#ff4444', label: 'Energy (J)', yAxisId: 'right' }
    ]
  },
  {
    id: 'exp-04-driven-damped-oscillation',
    title: 'Driven Damped Harmonic Oscillations',
    description: 'Study resonance and phase relationships in driven damped oscillators.',
    thumbnail: 'https://picsum.photos/seed/oscillation/400/225',
    usdPath: '/home/zhiren/Isaaclab_Assets/Experiment/exp.usd',
    experimentNumber: '4',
    difficulty: 'Medium',
    isLocked: false,
    controls: [
      { id: 'damping', label: 'Damping Coefficient', type: 'slider', min: 0, max: 2, step: 0.1, defaultValue: 0.5, command: 'set_damping' },
      { id: 'drive_frequency', label: 'Drive Frequency (Hz)', type: 'slider', min: 0.1, max: 5, step: 0.1, defaultValue: 1.0, command: 'set_frequency' },
      { id: 'run', label: 'Run', type: 'button', command: 'start_simulation' },
      { id: 'reset', label: 'Reset', type: 'button', command: 'reset' }
    ],
    chartConfig: [
      { key: 'displacement', color: '#D4AF37', label: 'Displacement (m)', yAxisId: 'left' },
      { key: 'amplitude', color: '#888888', label: 'Amplitude', yAxisId: 'right' }
    ]
  },
  {
    id: 'exp-05-rotational-inertia',
    title: 'Rotational Inertia (Physical Pendulum)',
    description: 'Determine rotational inertia through physical pendulum period measurements.',
    thumbnail: 'https://picsum.photos/seed/inertia/400/225',
    usdPath: '/home/zhiren/Isaaclab_Assets/Experiment/exp.usd',
    experimentNumber: '5',
    difficulty: 'Medium',
    isLocked: false,
    controls: [
      { id: 'pivot_position', label: 'Pivot Position (cm)', type: 'slider', min: 5, max: 50, step: 1, defaultValue: 25, command: 'set_pivot' },
      { id: 'angle', label: 'Initial Angle (°)', type: 'slider', min: 5, max: 30, step: 1, defaultValue: 10, command: 'set_angle' },
      { id: 'run', label: 'Run', type: 'button', command: 'start_simulation' },
      { id: 'reset', label: 'Reset', type: 'button', command: 'reset' }
    ],
    chartConfig: [
      { key: 'period', color: '#a855f7', label: 'Period (s)', yAxisId: 'left' },
      { key: 'inertia', color: '#00f3ff', label: 'Moment of Inertia', yAxisId: 'right' }
    ]
  },
  {
    id: 'exp-06-centripetal-force',
    title: 'Centripetal Force',
    description: 'Investigate the relationship between centripetal force, mass, and circular motion.',
    thumbnail: 'https://picsum.photos/seed/centripetal/400/225',
    usdPath: '/home/zhiren/Isaaclab_Assets/Experiment/exp.usd',
    experimentNumber: '6',
    difficulty: 'Easy',
    isLocked: false,
    controls: [
      { id: 'mass', label: 'Mass (kg)', type: 'slider', min: 0.1, max: 2, step: 0.1, defaultValue: 0.5, command: 'set_mass' },
      { id: 'radius', label: 'Radius (m)', type: 'slider', min: 0.1, max: 1, step: 0.05, defaultValue: 0.3, command: 'set_radius' },
      { id: 'angular_velocity', label: 'Angular Velocity (rad/s)', type: 'slider', min: 1, max: 10, step: 0.5, defaultValue: 5, command: 'set_angular_velocity' },
      { id: 'run', label: 'Run', type: 'button', command: 'start_simulation' },
      { id: 'reset', label: 'Reset', type: 'button', command: 'reset' }
    ],
    chartConfig: [
      { key: 'centripetal_force', color: '#fb923c', label: 'Centripetal Force (N)', yAxisId: 'left' },
      { key: 'tension', color: '#ff4444', label: 'String Tension (N)', yAxisId: 'right' }
    ]
  },
  {
    id: 'exp-07-momentum-conservation',
    title: 'Conservation of Momentum',
    description: 'Verify momentum conservation in elastic and inelastic collisions.',
    thumbnail: 'https://picsum.photos/seed/momentum/400/225',
    usdPath: '/home/zhiren/Isaaclab_Assets/Experiment/exp.usd',
    experimentNumber: '7',
    difficulty: 'Easy',
    isLocked: false,
    controls: [
      { id: 'mass1', label: 'Mass 1 (kg)', type: 'slider', min: 0.1, max: 5, step: 0.1, defaultValue: 1.0, command: 'set_mass1' },
      { id: 'mass2', label: 'Mass 2 (kg)', type: 'slider', min: 0.1, max: 5, step: 0.1, defaultValue: 1.0, command: 'set_mass2' },
      { id: 'velocity1', label: 'Initial Velocity 1 (m/s)', type: 'slider', min: 0, max: 10, step: 0.5, defaultValue: 5, command: 'set_velocity1' },
      { id: 'elasticity', label: 'Coefficient of Restitution', type: 'slider', min: 0, max: 1, step: 0.1, defaultValue: 1, command: 'set_elasticity' },
      { id: 'run', label: 'Run', type: 'button', command: 'start_simulation' },
      { id: 'reset', label: 'Reset', type: 'button', command: 'reset' }
    ],
    chartConfig: [
      { key: 'total_momentum', color: '#10b981', label: 'Total Momentum', yAxisId: 'left' },
      { key: 'kinetic_energy', color: '#ff0000', label: 'Kinetic Energy (J)', yAxisId: 'right' }
    ]
  },
  {
    id: 'exp-08-resonance-air-column',
    title: 'Resonance in Air Column',
    description: 'Study standing waves and resonance frequencies in air columns.',
    thumbnail: 'https://picsum.photos/seed/resonance/400/225',
    usdPath: '/home/zhiren/Isaaclab_Assets/Experiment/exp.usd',
    experimentNumber: '8',
    difficulty: 'Medium',
    isLocked: false,
    controls: [
      { id: 'length', label: 'Column Length (cm)', type: 'slider', min: 10, max: 100, step: 1, defaultValue: 50, command: 'set_length' },
      { id: 'frequency', label: 'Frequency (Hz)', type: 'slider', min: 100, max: 2000, step: 50, defaultValue: 512, command: 'set_frequency' },
      { id: 'run', label: 'Generate Tone', type: 'button', command: 'start_simulation' },
      { id: 'reset', label: 'Reset', type: 'button', command: 'reset' }
    ],
    chartConfig: [
      { key: 'amplitude', color: '#ec4899', label: 'Sound Amplitude', yAxisId: 'left' },
      { key: 'resonance_peaks', color: '#ffffff', label: 'Resonance Peaks', yAxisId: 'right' }
    ]
  }
];