import React, {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react';
import { AccessibilityInfo, useColorScheme } from 'react-native';

import { darkColors, lightColors, type ColorScheme } from './colors';
import { elevation, motion, radii, spacing, typography } from './tokens';

export interface Theme {
  mode: 'light' | 'dark';
  colors: ColorScheme;
  spacing: typeof spacing;
  radii: typeof radii;
  typography: typeof typography;
  elevation: typeof elevation;
  /** true إذا فعّلت المستخدمة «تقليل الحركة» في إعدادات iOS. */
  reduceMotion: boolean;
  /** مدّة الانتقال بعد احترام تفضيل تقليل الحركة. */
  duration: (key: keyof typeof motion) => number;
}

const ThemeContext = createContext<Theme | null>(null);

interface ThemeProviderProps {
  children: ReactNode;
  /** فرض وضع معيّن — للاختبارات وللمعاينة فقط. */
  forcedMode?: 'light' | 'dark';
  /** فرض تقليل الحركة — للاختبارات. */
  forcedReduceMotion?: boolean;
}

export function ThemeProvider({
  children,
  forcedMode,
  forcedReduceMotion,
}: ThemeProviderProps): React.JSX.Element {
  const systemScheme = useColorScheme();
  const [reduceMotion, setReduceMotion] = useState<boolean>(forcedReduceMotion ?? false);

  useEffect(() => {
    if (forcedReduceMotion !== undefined) {
      return;
    }
    let alive = true;
    void AccessibilityInfo.isReduceMotionEnabled().then((enabled) => {
      if (alive) {
        setReduceMotion(enabled);
      }
    });
    const sub = AccessibilityInfo.addEventListener('reduceMotionChanged', (enabled) => {
      setReduceMotion(enabled);
    });
    return () => {
      alive = false;
      sub.remove();
    };
  }, [forcedReduceMotion]);

  const mode: 'light' | 'dark' = forcedMode ?? (systemScheme === 'dark' ? 'dark' : 'light');

  const value = useMemo<Theme>(
    () => ({
      mode,
      colors: mode === 'dark' ? darkColors : lightColors,
      spacing,
      radii,
      typography,
      elevation,
      reduceMotion,
      duration: (key) => (reduceMotion ? motion.reduced : motion[key]),
    }),
    [mode, reduceMotion],
  );

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useTheme(): Theme {
  const theme = useContext(ThemeContext);
  if (theme === null) {
    throw new Error('useTheme يجب أن يُستدعى داخل ThemeProvider.');
  }
  return theme;
}
