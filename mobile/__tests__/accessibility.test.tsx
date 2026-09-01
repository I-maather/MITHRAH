import React from 'react';
import type { ReactTestInstance } from 'react-test-renderer';
import { act, screen } from '@testing-library/react-native';

import AuditScreen from '../app/(app)/audit';
import ChartScreen from '../app/(app)/chart';
import DecisionScreen from '../app/(app)/decision';
import EmergencyScreen from '../app/(app)/emergency';
import HomeScreen from '../app/(app)/home';
import IntelligenceScreen from '../app/(app)/intelligence';
import NotificationsScreen from '../app/(app)/notifications';
import PerformanceScreen from '../app/(app)/performance';
import PositionScreen from '../app/(app)/position';
import ProfilesScreen from '../app/(app)/profiles';
import ProvidersScreen from '../app/(app)/providers';
import ScanScreen from '../app/(app)/scan';
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
  ['ماذا رأيتُ اليوم', ScanScreen],
  ['الشموع والمستويات', ChartScreen],
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

  /**
   * ⚠️ **تغيير مُعلَن (2026-09-01): الفحص صار سلوكياً بدل أن يكون على الدور.**
   *
   * كان يشترط ألّا يوجد **أي** عنصرٍ بدورٍ تفاعلي في شاشات القراءة. وهو
   * حارسٌ على الشكل لا على المعنى، وأوسع من اسمه: صفُّ انتقالٍ يفتح شاشة،
   * وزرُّ اختيار أداةٍ يبدّل ما يُعرَض — وليس أيٌّ منهما فعلاً على النظام.
   * وحين أُضيفت صفوف الانتقال (علاجاً لعشر شاشاتٍ لا يصل إليها أحد) وزرُّ
   * اختيار الأداة في شاشة الشموع، أسقطهما الفحص وهما بريئان.
   *
   * والمقصود الحقيقي أن **شاشة القراءة لا تغيّر شيئاً في النظام**. وهذا
   * يُقاس بما يخرج إلى الشبكة لا بدور العنصر: كل تغييرٍ في هذا التطبيق يمرّ
   * بـ`POST` على مسارٍ مُعلَن، بلا استثناء (`src/api/client.ts`).
   *
   * فالفحص الآن **أقوى**: يضغط كل عنصرٍ تفاعلي في الشاشة، ثم يشترط أن كل ما
   * خرج إلى الشبكة كان `GET`. ولو أضاف أحدٌ يوماً زرّ إغلاق مركزٍ في شاشة
   * «المركز الحالي» لسقط هنا، وهو ما كان الفحص القديم يمنعه — مع أنه كان
   * يسقط أيضاً على زرٍّ لا يفعل شيئاً.
   */
  it('شاشات القراءة لا يخرج منها إلا GET — ولو ضُغط كل ما فيها', async () => {
    for (const Component of [
      DecisionScreen,
      ProfilesScreen,
      PositionScreen,
      HistoryScreen,
      PerformanceScreen,
      ProvidersScreen,
      NotificationsScreen,
      AuditScreen,
      ScanScreen,
      ChartScreen,
    ]) {
      const seen: string[] = [];
      const fetchImpl = jest.fn(async (_url: unknown, init?: { method?: string }) => {
        seen.push(init?.method ?? 'GET');
        // استجابة لا تطابق الغلاف: العميل يرفضها، والشاشة تعرض خطأً —
        // وهذا كافٍ، فالمقصود ما خرج لا ما عاد.
        return { ok: true, status: 200, json: async () => ({}) } as unknown as Response;
      });

      const view = renderWithHarness(<Component />, {
        status: 'UNLOCKED',
        fetchImpl: fetchImpl as unknown as typeof fetch,
      });

      for (const node of interactiveNodes(view)) {
        await act(async () => {
          (node.props.onPress as undefined | (() => void))?.();
        });
      }

      expect(seen.filter((method) => method !== 'GET')).toEqual([]);
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
