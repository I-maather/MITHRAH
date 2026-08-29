import React from 'react';
import { Pressable, ScrollView, Text, View } from 'react-native';

/**
 * حارس الانهيار — يمنع **الشاشة السوداء**.
 *
 * ## لماذا وُجد
 *
 * انهار التطبيق إلى شاشة سوداء صمّاء لأن الخادم أرسل `kill_switch_active`
 * والتطبيق يقرأ `kill_switch.active`. وخطأ التصيير في React يُفكّك الشجرة
 * كاملة إن لم يوجد حاجز، فلا يبقى على الشاشة شيء — **ولا رسالة**.
 *
 * وشاشة سوداء في تطبيق يراقب مالاً هي أسوأ فشل ممكن: لا تقول «تعطّلت»،
 * تقول لا شيء. والمالكة لا تعرف أموقوفٌ التداول أم يعمل.
 *
 * ## لماذا بلا مكوّنات المشروع ولا `useTheme`
 *
 * هذه آخر شاشة تُعرض حين ينهار كل شيء، **فلا يجوز أن تعتمد على شيء قد
 * يكون هو المنهار**. `Text` و`Button` عندنا يقرآن السمة من سياق، فلو كان
 * العطب في السمة نفسها لانهار حارس الانهيار. فكل ما هنا من `react-native`
 * مباشرةً، وألوانه مكتوبة صراحةً.
 *
 * ## ما يقوله أولاً
 *
 * **أن التطبيق لا يأذن بتنفيذ.** ما دام لا يأمر بشيء، فعطبه لا يفتح مركزاً
 * ولا يغلقه، والحدود وقاطع الطوارئ مفروضة على الخادم. هذه أهم جملة على
 * الشاشة، فتأتي قبل أي شيء آخر.
 *
 * ## وما لا يعرضه
 *
 * **نصّ الخطأ التقني** — إلا في التطوير. نصوص الأخطاء تحمل مسارات وأسماء
 * حقول. ولا يبتلع الخطأ صامتاً: يُمرَّر إلى `onError` كي يُسجَّل.
 */

/** ألوان مكتوبة صراحةً: شاشة الطوارئ لا تسأل السمة عن شيء. */
const NIGHT = '#211056';
const SURFACE = '#2C1A6B';
const INK = '#F4F1FF';
const MUTED = '#B9AEE4';
const ACCENT = '#4CC9F0';

interface Props {
  children: React.ReactNode;
  /** يُستدعى عند الإمساك — للتسجيل. لا يُغيّر ما يُعرض. */
  onError?: (error: Error) => void;
  /** في التطوير يُعرض نصّ الخطأ. في الإصدار لا يُعرض. */
  showDetail?: boolean;
}

interface State {
  error: Error | null;
}

export class CrashGuard extends React.Component<Props, State> {
  override state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  override componentDidCatch(error: Error): void {
    this.props.onError?.(error);
  }

  private reset = (): void => {
    this.setState({ error: null });
  };

  override render(): React.ReactNode {
    const { error } = this.state;
    if (error === null) {
      return this.props.children;
    }

    const detail = this.props.showDetail ?? __DEV__;

    return (
      <ScrollView
        testID="crash-guard"
        style={{ flex: 1, backgroundColor: NIGHT }}
        contentContainerStyle={{ padding: 20, paddingTop: 72, gap: 16, flexGrow: 1 }}
      >
        <Text
          accessibilityRole="header"
          style={{ color: INK, fontSize: 26, fontWeight: '700', textAlign: 'right' }}
        >
          تعطّلت الشاشة
        </Text>

        {/* **أول ما يُقال، لأنه أهم ما يُقال.** */}
        <View style={{ backgroundColor: SURFACE, borderRadius: 14, padding: 16, gap: 8 }}>
          <Text
            testID="crash-guard-safety"
            style={{ color: INK, fontSize: 16, fontWeight: '700', textAlign: 'right' }}
          >
            التطبيق لا يأذن بتنفيذ، ولا يفتح مركزاً ولا يغلقه.
          </Text>
          <Text style={{ color: MUTED, fontSize: 13, textAlign: 'right', lineHeight: 20 }}>
            الحدود وقاطع الطوارئ تُفرَض على الخادم ولا تتأثّر بعطبٍ هنا.
            هذا عطل في العرض وحده.
          </Text>
        </View>

        <Text
          testID="crash-guard-body"
          style={{ color: MUTED, fontSize: 15, textAlign: 'right', lineHeight: 24 }}
        >
          تعذّر عرض هذه الشاشة. جرّبي إعادة المحاولة، ولو تكرّر فالسبب غالباً
          اختلاف بين نسخة التطبيق ونسخة الخادم — أعيدي تشغيل الخادم، أو ابني
          التطبيق من جديد.
        </Text>

        {detail ? (
          <Text
            testID="crash-guard-detail"
            style={{ color: MUTED, fontSize: 11, textAlign: 'left' }}
          >
            {String(error?.message ?? error)}
          </Text>
        ) : null}

        <Pressable
          testID="crash-guard-retry"
          accessibilityRole="button"
          accessibilityLabel="إعادة المحاولة"
          onPress={this.reset}
          style={{
            backgroundColor: ACCENT,
            borderRadius: 14,
            paddingVertical: 14,
            alignItems: 'center',
          }}
        >
          <Text style={{ color: NIGHT, fontSize: 16, fontWeight: '700' }}>
            إعادة المحاولة
          </Text>
        </Pressable>
      </ScrollView>
    );
  }
}

export default CrashGuard;
