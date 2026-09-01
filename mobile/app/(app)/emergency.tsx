import React, { useState } from 'react';
import { View } from 'react-native';

import { ApiError } from '@/api/client';
import { useSession } from '@/auth/SessionProvider';
import { Banner, Card, ConfirmButton, Screen, Text } from '@/components';
import { isPreviewMode } from '@/fixtures';
import { t } from '@/i18n';
import { useTheme } from '@/theme';

/**
 * الطوارئ — ثلاثة إجراءات تقلّل المخاطرة، وواحدٌ يستأنف.
 *
 *     pause/request         إيقاف مؤقت          ↓ يقلّل
 *     killswitch/activate   قاطع الطوارئ         ↓ يقلّل
 *     device/revoke         إلغاء الجهاز         ↓ يقلّل
 *     pause/resume          استئناف التداول      ↑ **يزيد**
 *
 * لا يوجد في هذه الشاشة — ولا في التطبيق كله — إجراءٌ يفتح قفلاً: لا إلغاء
 * للقاطع، ولا إعادة تفعيل لمفتاح وسيط، ولا رفع لملف المخاطرة، ولا إغلاق مركز.
 *
 * والاستئناف يرفع **الإيقاف المحلي وحده**. فأسوأ ما يفعله مهاجم يمسك هذا
 * الهاتف مفتوحاً أن يعيد النظام من «موقوف» إلى «يقيّم» — ولا يستطيع بعدها
 * إرسال أمرٍ واحد، لأن الأقفال الأربعة الباقية لا تُمسّ من هنا.
 *
 * ## لماذا التأكيد على الثلاثة يختلف عن التأكيد على الرابع
 *
 * التأكيد بخطوتين على المقلِّلات يحمي من **الضغط الخاطئ** لا من المهاجم،
 * لأن الإجراء نفسه ليس ما يُهاجَم به. أمّا الاستئناف فيطلب فوقه **عبارةً
 * كاملة يفرضها الخادم**: زرٌّ يُضغط بالخطأ في الجيب لا يكتب جملة.
 */
type ActionKey = 'pause' | 'kill' | 'revoke' | 'resume';

export default function EmergencyScreen(): React.JSX.Element {
  const theme = useTheme();
  const { client, markRevoked } = useSession();
  const [busy, setBusy] = useState<ActionKey | null>(null);
  const [result, setResult] = useState<{ key: ActionKey; ok: boolean; messageAr: string } | null>(
    null,
  );

  const run = async (key: ActionKey): Promise<void> => {
    setBusy(key);
    setResult(null);
    try {
      if (key === 'pause') {
        const response = await client.requestPause();
        setResult({
          key,
          ok: response.data.accepted,
          messageAr: response.data.accepted ? t.emergency.pauseDone : t.emergency.failed,
        });
      } else if (key === 'kill') {
        const response = await client.activateKillSwitch();
        setResult({
          key,
          ok: response.data.accepted,
          messageAr: response.data.accepted
            ? `${t.emergency.killDone} ${response.data.note_ar}`
            : t.emergency.failed,
        });
      } else if (key === 'resume') {
        const response = await client.resumeTrading();
        setResult({
          key,
          ok: response.data.accepted,
          messageAr: response.data.accepted
            ? `${t.emergency.resumeDone} ${response.data.note_ar}`
            : t.emergency.failed,
        });
      } else {
        const response = await client.revokeDevice();
        setResult({
          key,
          ok: response.data.accepted,
          messageAr: response.data.accepted ? t.emergency.revokeDone : t.emergency.failed,
        });
        if (response.data.accepted) {
          // الجهاز أُلغي: تُمحى الرموز محلياً فوراً ولا يُنتظر انتهاء المهلة.
          await markRevoked();
        }
      }
    } catch (caught) {
      const messageAr =
        caught instanceof ApiError ? caught.messageAr : t.emergency.failed;
      setResult({ key, ok: false, messageAr });
    } finally {
      setBusy(null);
    }
  };

  return (
    <Screen testID="emergency-screen" title={t.emergency.title} preview={isPreviewMode()}>
      <Banner
        testID="emergency-intro-banner"
        tone="info"
        title="ثلاثة إجراءات فقط"
        body={t.emergency.intro}
      />

      {result !== null ? (
        <Banner
          testID="emergency-result"
          tone={result.ok ? 'positive' : 'negative'}
          title={result.messageAr}
        />
      ) : null}

      <Card testID="pause-card" title={t.emergency.pause}>
        <Text variant="caption" tone="secondary">
          {t.emergency.pauseBody}
        </Text>
        <ConfirmButton
          testID="pause-action"
          label={t.emergency.pause}
          tone="caution"
          busy={busy === 'pause'}
          accessibilityLabel={t.emergency.pause}
          accessibilityHint={t.emergency.pauseBody}
          confirmTitle={t.emergency.pause}
          confirmBody={t.emergency.pauseBody}
          confirmLabel={t.emergency.pauseConfirm}
          onConfirm={() => {
            void run('pause');
          }}
        />
      </Card>

      <Card testID="kill-card" title={t.emergency.kill}>
        <Text variant="caption" tone="secondary">
          {t.emergency.killBody}
        </Text>
        <ConfirmButton
          testID="kill-action"
          label={t.emergency.kill}
          tone="negative"
          busy={busy === 'kill'}
          accessibilityLabel={t.emergency.kill}
          accessibilityHint={t.emergency.killBody}
          confirmTitle={t.emergency.killConfirmTitle}
          confirmBody={t.emergency.killConfirmBody}
          confirmLabel={t.emergency.killConfirm}
          onConfirm={() => {
            void run('kill');
          }}
        />
        <Text variant="micro" tone="tertiary" testID="kill-no-undo">
          لا يُلغى القاطع من هذا التطبيق. الإلغاء إجراء يزيد المخاطرة ويحتاج الخادم.
        </Text>
      </Card>

      <Card testID="revoke-card" title={t.emergency.revoke}>
        <Text variant="caption" tone="secondary">
          {t.emergency.revokeBody}
        </Text>
        <ConfirmButton
          testID="revoke-action"
          label={t.emergency.revoke}
          tone="negative"
          busy={busy === 'revoke'}
          accessibilityLabel={t.emergency.revoke}
          accessibilityHint={t.emergency.revokeBody}
          confirmTitle={t.emergency.revokeConfirmTitle}
          confirmBody={t.emergency.revokeConfirmBody}
          confirmLabel={t.emergency.revokeConfirm}
          onConfirm={() => {
            void run('revoke');
          }}
        />
      </Card>

      {/*
        الاستئناف آخر البطاقات عمداً: الترتيب في هذه الشاشة يقرأ من الأخفّ
        أثراً إلى الأثقل، ثم الوحيد الذي **يزيد** المخاطرة في النهاية —
        فلا تقع اليد عليه وهي تبحث عن الإيقاف.
      */}
      <Card testID="resume-card" title={t.emergency.resume}>
        <Text variant="caption" tone="secondary">
          {t.emergency.resumeBody}
        </Text>
        <ConfirmButton
          testID="resume-action"
          label={t.emergency.resume}
          tone="caution"
          busy={busy === 'resume'}
          accessibilityLabel={t.emergency.resume}
          accessibilityHint={t.emergency.resumeBody}
          confirmTitle={t.emergency.resumeConfirmTitle}
          confirmBody={t.emergency.resumeConfirmBody}
          confirmLabel={t.emergency.resumeConfirm}
          onConfirm={() => {
            void run('resume');
          }}
        />
      </Card>

      <View style={{ gap: theme.spacing.sm }}>
        {t.boundary.items.map((item) => (
          <Text key={item} variant="micro" tone="tertiary" accessibilityRole="text">
            {`× ${item}`}
          </Text>
        ))}
      </View>
    </Screen>
  );
}
