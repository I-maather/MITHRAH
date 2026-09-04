import { CameraView, useCameraPermissions } from 'expo-camera';
import { useRouter } from 'expo-router';
import React, { useRef, useState } from 'react';
import { TextInput, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { useSession } from '@/auth/SessionProvider';
import { enrolDevice } from '@/auth/enrolment';
import { publicIdentity } from '@/auth/identity';
import { Banner, Button, Card, Text } from '@/components';
import { t } from '@/i18n';
import { useTheme } from '@/theme';

/**
 * شاشة تسجيل الجهاز — مسح رمز الاقتران.
 *
 * ## ما لا يُعرض هنا
 *
 * **لا رقم ولا حالة نظام.** هذه الشاشة تسبق المصادقة، وأي بيان يظهر عليها
 * يُرى قبل Face ID. لا تعرض إلا حالة المسح نفسه.
 *
 * ## المسح مرة واحدة
 *
 * الكاميرا تُطلق الحدث لكل إطار تقرأ فيه رمزاً — عشرات المرات في الثانية.
 * وبلا قفل، يُرسَل التحدّي الواحد عشرات المرات: الأول ينجح، والبقية تُرفَض
 * ٤٠١ فتُعرَض للمالكة رسالة فشل فوق نجاح. القفل `handled` يمنع ذلك، وهو
 * `ref` لا `state` كي يُقرأ فوراً في نفس الإطار لا بعد إعادة التصيير.
 *
 * ## ولماذا لا يكفي `handled` وحده
 *
 * فتحُ القفل بعد الفشل — كي تُتاح محاولة أخرى — **يعيد فتح الباب على نفس
 * الرمز الباقي أمام العدسة**. فيُرسَل مئات المرات ويتجمّد الجهاز. حدث ذلك
 * فعلاً: 404 مكرّرة بلا نهاية في سجل الخادم.
 *
 * فيُحفَظ نصّ الرمز الذي رُفض ويُتجاهَل تماماً بعدها. ورمزٌ **جديد** يختلف
 * نصّه فيُعالَج فوراً بلا لمسة — وهو ما تحتاجه المالكة بالضبط.
 *
 * ## الاقتران على المحاكي
 *
 * المحاكي لا يملك كاميرا. فبلا مدخلٍ آخر لا يمكن **إطلاقاً** التحقّق من أن
 * التطبيق يعرض بيانات الخادم الحقيقية قبل تسليم بناءٍ إلى الجهاز — أي أن كل
 * دليلٍ بصريّ يبقى مؤجَّلاً إلى ما بعد التسليم، وهو عكس الترتيب الصحيح.
 *
 * فحقلُ لصقٍ يظهر تحت `__DEV__` وحده. وليس مساراً موازياً: الحمولة نفسها،
 * و`enrolDevice` نفسها، والتحدّي نفسه لمرةٍ واحدة، والخادم نفسه. المختلف هو
 * وسيلة نقل الحمولة إلى التطبيق — عدسةٌ هناك، حافظةٌ هنا.
 *
 * و`__DEV__` تُطوى إلى `false` في حزمة الإصدار، فيسقط الفرع كلّه من الحزمة
 * القابلة للتثبيت. يحرس ذلك اختبارٌ صريح.
 */
export default function EnrolScreen(): React.JSX.Element {
  const theme = useTheme();
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const { adoptSession, endpointTrusted, endpointReasonAr } = useSession();

  const [permission, requestPermission] = useCameraPermissions();
  const [busy, setBusy] = useState(false);
  const [failureAr, setFailureAr] = useState<string | null>(null);
  const handled = useRef(false);
  /** نصّ آخر رمز رُفض — لا يُعاد إرساله أبداً. */
  const rejectedRaw = useRef<string | null>(null);
  /** حقل اللصق — تطوير فقط. */
  const [pasted, setPasted] = useState('');

  const onScanned = async (raw: string): Promise<void> => {
    if (handled.current) {
      return;
    }
    // رمزٌ رُفض لن يُقبل بإعادة إرساله: منتهياً كان أو مُستهلَكاً أو
    // والخادم لا يعرف المسار. فيُتجاهَل بلا طلب شبكة.
    if (rejectedRaw.current === raw) {
      return;
    }
    handled.current = true;
    setBusy(true);
    setFailureAr(null);
    try {
      const identity = await publicIdentity();
      const result = await enrolDevice(raw, identity, t.enrol.deviceName);
      if (!result.ok || result.session === undefined) {
        rejectedRaw.current = raw;
        setFailureAr(result.reasonAr);
        // يُفتَح القفل لرمز **آخر**، لا لهذا الرمز — يمنعه `rejectedRaw`.
        handled.current = false;
        return;
      }
      await adoptSession(result.session);
      router.replace('/');
    } finally {
      setBusy(false);
    }
  };

  /**
   * اللصق — تطوير فقط. الشرط ثابتٌ يُطوى وقت البناء، فلا يبقى منه شيء في
   * حزمة الإصدار.
   */
  const devPaste = (): React.JSX.Element | null => {
    if (!__DEV__) {
      return null;
    }
    return (
      <Card testID="enrol-dev-paste">
        <Text variant="bodyStrong">{t.enrol.devPasteTitle}</Text>
        <Text variant="caption" tone="secondary">
          {t.enrol.devPasteBody}
        </Text>
        <TextInput
          testID="enrol-dev-paste-input"
          value={pasted}
          onChangeText={setPasted}
          placeholder={t.enrol.devPastePlaceholder}
          placeholderTextColor={theme.colors.textTertiary}
          autoCapitalize="none"
          autoCorrect={false}
          secureTextEntry
          style={{
            borderWidth: 1,
            borderColor: theme.colors.border,
            borderRadius: theme.radii.md,
            paddingHorizontal: theme.spacing.md,
            paddingVertical: theme.spacing.sm,
            color: theme.colors.textPrimary,
            marginTop: theme.spacing.sm,
          }}
        />
        <Button
          label={t.enrol.devPasteAction}
          accessibilityLabel={t.enrol.devPasteAction}
          testID="enrol-dev-paste-button"
          onPress={() => {
            const raw = pasted.trim();
            if (raw.length === 0) {
              setFailureAr(t.enrol.devPasteEmpty);
              return;
            }
            // القفلان نفسهما: لا يُعاد إرسال حمولةٍ رُفضت، ولا تُرسَل مرتين.
            handled.current = false;
            void onScanned(raw);
          }}
        />
      </Card>
    );
  };

  const body = (): React.JSX.Element => {
    if (!endpointTrusted) {
      return (
        <Banner
          testID="enrol-untrusted-endpoint"
          tone="negative"
          title={t.enrol.untrustedTitle}
          body={endpointReasonAr}
        />
      );
    }
    if (permission === null) {
      return <Text variant="body">{t.enrol.checkingPermission}</Text>;
    }
    if (!permission.granted) {
      return (
        <Card testID="enrol-permission-card">
          <Text variant="bodyStrong">{t.enrol.permissionTitle}</Text>
          <Text variant="caption" tone="secondary">
            {t.enrol.permissionBody}
          </Text>
          <Button
            label={t.enrol.permissionGrant}
            accessibilityLabel={t.enrol.permissionGrant}
            testID="enrol-permission-button"
            onPress={() => {
              void requestPermission();
            }}
          />
        </Card>
      );
    }
    return (
      <View
        testID="enrol-camera-frame"
        style={{
          aspectRatio: 1,
          borderRadius: theme.radii.lg,
          overflow: 'hidden',
          borderWidth: 2,
          borderColor: theme.colors.accent,
        }}
      >
        <CameraView
          testID="enrol-camera"
          style={{ flex: 1 }}
          facing="back"
          barcodeScannerSettings={{ barcodeTypes: ['qr'] }}
          onBarcodeScanned={({ data }) => {
            void onScanned(data);
          }}
        />
      </View>
    );
  };


  return (
    <View
      testID="enrol-screen"
      style={{
        flex: 1,
        backgroundColor: theme.colors.background,
        paddingHorizontal: theme.spacing.xl,
        paddingTop: insets.top + theme.spacing.xl,
        paddingBottom: insets.bottom + theme.spacing.xxl,
        gap: theme.spacing.lg,
      }}
    >
      <View style={{ gap: theme.spacing.sm }}>
        <Text variant="title" accessibilityRole="header">
          {t.enrol.title}
        </Text>
        <Text variant="body" tone="secondary">
          {t.enrol.subtitle}
        </Text>
      </View>

      {failureAr !== null ? (
        <Banner testID="enrol-failure" tone="negative" title={failureAr} />
      ) : null}

      {busy ? <Text variant="caption" tone="secondary">{t.enrol.working}</Text> : null}

      {devPaste()}

      {body()}

      <Text variant="micro" tone="tertiary" testID="enrol-note">
        {t.enrol.note}
      </Text>

      <Button
        label={t.enrol.back}
        accessibilityLabel={t.enrol.back}
        tone="neutral"
        testID="enrol-back"
        onPress={() => {
          router.replace('/');
        }}
      />
    </View>
  );
}
