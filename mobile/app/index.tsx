import React, { useEffect, useState } from 'react';
import { View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { useRouter } from 'expo-router';

import { readCapabilities, describeGate, type GateCapabilities } from '@/auth/biometrics';
import { useSession } from '@/auth/SessionProvider';
import { Banner, Button, Card, Text } from '@/components';
import { t } from '@/i18n';
import { useTheme } from '@/theme';

/**
 * شاشة الإقلاع الآمن — بوابة Face ID.
 *
 * FACE ID IS A LOCAL ACCESS GATE, NOT SERVER AUTHENTICATION.
 * Passing this screen unlocks the *display*. It grants no permission: every
 * request still carries the short-lived bearer token the server issued to this
 * enrolled device, and the server re-checks that token on every call. If the
 * device was revoked, the gate opens and the very next request returns 401 —
 * which lands the session back here. See `src/auth/biometrics.ts`.
 *
 * لا يظهر على هذه الشاشة أي رقم ولا حالة نظام: هي أول ما يُرى قبل المصادقة.
 */
export default function SecureLaunchScreen(): React.JSX.Element {
  const theme = useTheme();
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const { status, unlock, lastGateMessageAr, pendingDeepLink } = useSession();

  const [caps, setCaps] = useState<GateCapabilities | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let alive = true;
    void readCapabilities().then((value) => {
      if (alive) {
        setCaps(value);
      }
    });
    return () => {
      alive = false;
    };
  }, []);

  useEffect(() => {
    if (status === 'UNLOCKED') {
      router.replace('/(app)/home');
    }
  }, [status, router]);

  const onUnlock = async (): Promise<void> => {
    setBusy(true);
    try {
      await unlock();
    } finally {
      setBusy(false);
    }
  };

  const gateDescription = caps === null ? null : describeGate(caps);

  return (
    <View
      testID="secure-launch"
      style={{
        flex: 1,
        backgroundColor: theme.colors.background,
        paddingHorizontal: theme.spacing.xl,
        paddingTop: insets.top + theme.spacing.huge,
        paddingBottom: insets.bottom + theme.spacing.xxl,
        justifyContent: 'space-between',
        gap: theme.spacing.xxl,
      }}
    >
      <View style={{ gap: theme.spacing.sm, marginTop: theme.spacing.huge }}>
        <Text variant="display" accessibilityRole="header">
          {t.gate.title}
        </Text>
        <Text variant="body" tone="secondary">
          {t.app.tagline}
        </Text>
      </View>

      <View style={{ gap: theme.spacing.lg }}>
        {status === 'REVOKED' ? (
          <Banner
            testID="revoked-banner"
            tone="negative"
            title={t.gate.revokedTitle}
            body={t.gate.revokedBody}
          />
        ) : null}

        {status === 'NO_SESSION' ? (
          <Card testID="no-session-card">
            <Banner
              testID="no-session-banner"
              tone="caution"
              title={t.gate.noSessionTitle}
              body={t.gate.noSessionBody}
            />
            <Button
              label={t.gate.enrolAction}
              accessibilityLabel={t.gate.enrolAction}
              testID="enrol-button"
              onPress={() => {
                router.push('/enrol');
              }}
            />
          </Card>
        ) : null}

        {lastGateMessageAr !== null ? (
          <Banner testID="gate-message" tone="caution" title={lastGateMessageAr} />
        ) : null}

        {pendingDeepLink !== null ? (
          <Banner testID="deeplink-held" tone="info" title={t.gate.deepLinkHeld} />
        ) : null}

        <Card testID="gate-card">
          <Text variant="bodyStrong" testID="gate-locked-label">
            {t.gate.subtitle}
          </Text>
          {gateDescription !== null ? (
            <Text variant="caption" tone="secondary">
              {gateDescription}
            </Text>
          ) : null}
          <Text variant="caption" tone="secondary">
            {t.gate.fallbackNote}
          </Text>

          <Button
            label={t.gate.unlock}
            busy={busy}
            disabled={status === 'REVOKED' || status === 'NO_SESSION'}
            accessibilityLabel={t.gate.unlock}
            accessibilityHint={t.gate.faceIdNote}
            testID="unlock-button"
            onPress={() => {
              void onUnlock();
            }}
          />
        </Card>

        <Text variant="micro" tone="tertiary" testID="faceid-note">
          {t.gate.faceIdNote}
        </Text>
      </View>
    </View>
  );
}
