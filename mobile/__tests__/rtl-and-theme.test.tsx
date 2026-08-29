import React from 'react';
import { I18nManager, Text as RNText, View } from 'react-native';
import { render, screen } from '@testing-library/react-native';

import { Card, Field, StatusPill, Text } from '@/components';
import { applyRtl, rtlState } from '@/i18n';
import { ThemeProvider, darkColors, lightColors, useTheme } from '@/theme';
import { renderWithHarness } from './helpers';

/**
 * الاتجاه والوضعان.
 */

describe('من اليمين إلى اليسار', () => {
  it('يُطلب السماح بالاتجاه وفرضه عند الإقلاع', () => {
    const allow = jest.spyOn(I18nManager, 'allowRTL');
    const force = jest.spyOn(I18nManager, 'forceRTL');
    applyRtl();
    expect(allow).toHaveBeenCalledWith(true);
    if (!I18nManager.isRTL) {
      expect(force).toHaveBeenCalledWith(true);
    }
    allow.mockRestore();
    force.mockRestore();
  });

  it('لا يُفرض الاتجاه مرتين في العمر نفسه', () => {
    applyRtl();
    const allow = jest.spyOn(I18nManager, 'allowRTL');
    applyRtl();
    expect(allow).not.toHaveBeenCalled();
    allow.mockRestore();
  });

  it('يبلّغ عن حاجة إعادة التشغيل بدل الرسم باتجاه خاطئ صامتاً', () => {
    applyRtl();
    const state = rtlState();
    expect(state.restartRequired).toBe(!I18nManager.isRTL);
    if (state.restartRequired) {
      expect(state.noticeAr).toContain('اليمين إلى اليسار');
    } else {
      expect(state.noticeAr).toBeNull();
    }
  });

  it('كل نصّ يُرسم باتجاه rtl صراحةً', () => {
    renderWithHarness(<Text testID="sample">اختبار</Text>, { status: 'UNLOCKED' });
    const node = screen.getByTestId('sample');
    const style = Array.isArray(node.props.style) ? node.props.style.flat() : [node.props.style];
    const merged = Object.assign({}, ...style.filter(Boolean));
    expect(merged.writingDirection).toBe('rtl');
  });
});

describe('الوضعان الفاتح والداكن', () => {
  function Probe(): React.JSX.Element {
    const theme = useTheme();
    return (
      <View testID="probe" style={{ backgroundColor: theme.colors.background }}>
        <RNText testID="probe-mode">{theme.mode}</RNText>
      </View>
    );
  }

  it('الوضع الفاتح يستعمل لوحة الورق', () => {
    render(
      <ThemeProvider forcedMode="light" forcedReduceMotion>
        <Probe />
      </ThemeProvider>,
    );
    expect(screen.getByTestId('probe-mode')).toHaveTextContent('light');
    expect(screen.getByTestId('probe').props.style.backgroundColor).toBe(lightColors.background);
  });

  it('الوضع الداكن يستعمل لوحة الليل', () => {
    render(
      <ThemeProvider forcedMode="dark" forcedReduceMotion>
        <Probe />
      </ThemeProvider>,
    );
    expect(screen.getByTestId('probe-mode')).toHaveTextContent('dark');
    expect(screen.getByTestId('probe').props.style.backgroundColor).toBe(darkColors.background);
  });

  it('كل دور لوني مُعرَّف في الوضعين', () => {
    const lightKeys = Object.keys(lightColors).sort();
    const darkKeys = Object.keys(darkColors).sort();
    expect(darkKeys).toEqual(lightKeys);
    for (const key of lightKeys) {
      const record = lightColors as unknown as Record<string, string>;
      const darkRecord = darkColors as unknown as Record<string, string>;
      expect(record[key]).toBeTruthy();
      expect(darkRecord[key]).toBeTruthy();
    }
  });

  it('البطاقة والشارة تُرسمان في الوضعين بلا انهيار', () => {
    for (const mode of ['light', 'dark'] as const) {
      const view = render(
        <ThemeProvider forcedMode={mode} forcedReduceMotion>
          <Card title="عنوان" testID={`card-${mode}`}>
            <Field label="قيمة" value="1.00" />
            <StatusPill label="يعمل" tone="positive" testID={`pill-${mode}`} />
          </Card>
        </ThemeProvider>,
      );
      expect(view.getByTestId(`card-${mode}`)).toBeTruthy();
      expect(view.getByTestId(`pill-${mode}`)).toBeTruthy();
      view.unmount();
    }
  });
});

describe('تقليل الحركة', () => {
  function MotionProbe(): React.JSX.Element {
    const theme = useTheme();
    return <RNText testID="duration">{String(theme.duration('base'))}</RNText>;
  }

  it('يُصفّر مدد الانتقال حين يكون مفعّلاً', () => {
    render(
      <ThemeProvider forcedMode="light" forcedReduceMotion>
        <MotionProbe />
      </ThemeProvider>,
    );
    expect(screen.getByTestId('duration')).toHaveTextContent('0');
  });

  it('يستعمل المدّة المعتادة حين يكون مطفأً', () => {
    render(
      <ThemeProvider forcedMode="light" forcedReduceMotion={false}>
        <MotionProbe />
      </ThemeProvider>,
    );
    expect(screen.getByTestId('duration')).toHaveTextContent('220');
  });
});

describe('Dynamic Type', () => {
  it('تكبير الخط مفعّل دائماً وله سقف مناسب لكل مقاس', () => {
    renderWithHarness(
      <>
        <Text testID="body-text" variant="body">
          متن
        </Text>
        <Text testID="display-text" variant="display">
          عنوان
        </Text>
      </>,
      { status: 'UNLOCKED' },
    );
    const body = screen.getByTestId('body-text');
    const display = screen.getByTestId('display-text');
    expect(body.props.allowFontScaling).toBe(true);
    expect(display.props.allowFontScaling).toBe(true);
    // العنوان الكبير يُحدّ أكثر من المتن كي لا يدفع الأرقام خارج الشاشة.
    expect(display.props.maxFontSizeMultiplier).toBeLessThan(
      body.props.maxFontSizeMultiplier,
    );
    expect(body.props.maxFontSizeMultiplier).toBeGreaterThanOrEqual(2);
  });
});
