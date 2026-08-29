import { CameraView, useCameraPermissions } from 'expo-camera';
import { useRouter } from 'expo-router';
import React, { useRef, useState } from 'react';
import { View } from 'react-native';
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

  const onScanned = async (raw: string): Promise<void> => {
    if (handled.current) {
      return;
    }
    handled.current = true;
    setBusy(true);
    setFailureAr(null);
    try {
      const identity = await publicIdentity();
      const result = await enrolDevice(raw, identity, t.enrol.deviceName);
      if (!result.ok || result.session === undefined) {
        setFailureAr(result.reasonAr);
        // يُسمح بمحاولة أخرى: الفشل هنا غالباً رمز منتهٍ، لا خطأ دائم.
        handled.current = false;
        return;
      }
      await adoptSession(result.session);
      router.replace('/');
    } finally {
      setBusy(false);
    }
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
