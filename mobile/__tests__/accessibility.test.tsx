import React from 'react';
import type { ReactTestInstance } from 'react-test-renderer';
import { screen } from '@testing-library/react-native';

import AuditScreen from '../app/(app)/audit';
import DecisionScreen from '../app/(app)/decision';
import EmergencyScreen from '../app/(app)/emergency';
import HomeScreen from '../app/(app)/home';
import IntelligenceScreen from '../app/(app)/intelligence';
import NotificationsScreen from '../app/(app)/notifications';
import PerformanceScreen from '../app/(app)/performance';
import PositionScreen from '../app/(app)/position';
import ProfilesScreen from '../app/(app)/profiles';
import ProvidersScreen from '../app/(app)/providers';
import SettingsScreen from '../app/(app)/settings';
import SystemScreen from '../app/(app)/system';
import HistoryScreen from '../app/(app)/history';
import { MIN_TOUCH_TARGET } from '@/theme';
import { renderWithHarness } from './helpers';

/**
 * الوصولية.
 *
 * القاعدة المفروضة هنا: **كل عنصر تفاعلي يحمل تسمية منطوقة**. زر بلا تسمية على
 * شاشة طوارئ هو زر لا يمكن الوثوق بالضغط عليه دون نظر.
 */

const SCREENS: Array<[string, React.ComponentType]> = [
  ['الرئيسية', HomeScreen],
  ['قراءة السوق', IntelligenceScreen],
  ['تفصيل القرار', DecisionScreen],
  ['ملفات المخاطرة', ProfilesScreen],
  ['المركز الحالي', PositionScreen],
  ['سجل الصفقات', HistoryScreen],
  ['الأداء', PerformanceScreen],
  ['المزوّدون', ProvidersScreen],
  ['الإشعارات', NotificationsScreen],
  ['التدقيق', AuditScreen],
  ['النظام', SystemScreen],
  ['الإعدادات', SettingsScreen],
  ['الطوارئ', EmergencyScreen],
];

const INTERACTIVE_ROLES = ['button', 'link', 'radio', 'switch', 'checkbox'];

const interactiveNodes = (view: ReturnType<typeof renderWithHarness>): ReactTestInstance[] =>
  view.UNSAFE_root.findAll((node: ReactTestInstance) => {
    const role = node.props?.accessibilityRole;
    return typeof role === 'string' && INTERACTIVE_ROLES.includes(role);
  });

describe('كل عنصر تفاعلي منطوق', () => {
  /**
   * لا يُشترط وجود عنصر تفاعلي: أكثر الشاشات هنا **قراءة محضة** بلا زر واحد،
   * وهذا هو المقصود. المشترط أن كل عنصر تفاعلي موجود يحمل تسمية منطوقة.
   */
  it.each(SCREENS)('%s', (_name, Component) => {
    const view = renderWithHarness(<Component />, { status: 'UNLOCKED' });
    for (const node of interactiveNodes(view)) {
      const label = node.props.accessibilityLabel;
      expect(typeof label).toBe('string');
      expect(String(label).trim().length).toBeGreaterThan(0);
    }
    view.unmount();
  });

  it('الشاشات التي تحمل أفعالاً تحمل تسميات لها', () => {
    for (const Component of [HomeScreen, SettingsScreen, EmergencyScreen]) {
      const view = renderWithHarness(<Component />, { status: 'UNLOCKED' });
      const nodes = interactiveNodes(view);
      expect(nodes.length).toBeGreaterThan(0);
      for (const node of nodes) {
        expect(String(node.props.accessibilityLabel).trim().length).toBeGreaterThan(0);
      }
      view.unmount();
    }
  });

  it('شاشات القراءة المحضة لا تحمل أي فعل', () => {
    for (const Component of [
      DecisionScreen,
      ProfilesScreen,
      PositionScreen,
      HistoryScreen,
      PerformanceScreen,
      ProvidersScreen,
      NotificationsScreen,
      AuditScreen,
    ]) {
      const view = renderWithHarness(<Component />, { status: 'UNLOCKED' });
      expect(interactiveNodes(view)).toHaveLength(0);
      view.unmount();
    }
  });
});

describe('مساحات اللمس', () => {
  it('كل زر في شاشة الطوارئ يبلغ الحد الأدنى', () => {
    const view = renderWithHarness(<EmergencyScreen />, { status: 'UNLOCKED' });
    const buttons = view.UNSAFE_root.findAll(
      (node: ReactTestInstance) => node.props?.accessibilityRole === 'button',
    );
    for (const button of buttons) {
      const style =
        typeof button.props.style === 'function'
          ? button.props.style({ pressed: false })
          : button.props.style;
      const merged = Array.isArray(style) ? Object.assign({}, ...style.filter(Boolean)) : style;
      expect(merged.minHeight).toBeGreaterThanOrEqual(MIN_TOUCH_TARGET);
    }
  });
});

describe('العناوين مُعلَنة', () => {
  it('كل شاشة تُعلن عنواناً واحداً على الأقل بوصفه header', () => {
    for (const [, Component] of SCREENS) {
      const view = renderWithHarness(<Component />, { status: 'UNLOCKED' });
      const headers = view.UNSAFE_root.findAll(
        (node: ReactTestInstance) => node.props?.accessibilityRole === 'header',
      );
      expect(headers.length).toBeGreaterThan(0);
      view.unmount();
    }
  });
});

describe('الحالة لا تُحمَّل على اللون وحده', () => {
  it('كل شارة حالة تحمل نصّاً منطوقاً', () => {
    renderWithHarness(<HomeScreen />, { status: 'UNLOCKED' });
    const pill = screen.getByTestId('system-state-pill');
    expect(String(pill.props.accessibilityLabel).trim().length).toBeGreaterThan(0);
  });
});
