import React, { useState } from 'react';
import { ActivityIndicator, Pressable, View } from 'react-native';

import { t } from '@/i18n';
import { MIN_TOUCH_TARGET, toneOf, useTheme, type ToneName } from '@/theme';
import { Text } from './Text';

type ButtonKind = 'primary' | 'secondary' | 'quiet';

interface ButtonProps {
  label: string;
  onPress: () => void;
  kind?: ButtonKind;
  tone?: ToneName;
  disabled?: boolean;
  busy?: boolean;
  /**
   * تسمية VoiceOver. **إلزامية** لكل عنصر تفاعلي في هذا التطبيق:
   * `__tests__/accessibility.test.tsx` يتحقق منها.
   */
  accessibilityLabel: string;
  accessibilityHint?: string;
  testID?: string;
}

export function Button({
  label,
  onPress,
  kind = 'primary',
  tone = 'accent',
  disabled = false,
  busy = false,
  accessibilityLabel,
  accessibilityHint,
  testID,
}: ButtonProps): React.JSX.Element {
  const theme = useTheme();
  const { fg, bg } = toneOf(theme.colors, tone);
  const inert = disabled || busy;

  const background =
    kind === 'primary' ? fg : kind === 'secondary' ? bg : 'transparent';
  const border = kind === 'quiet' ? theme.colors.border : 'transparent';
  const labelColor = kind === 'primary' ? theme.colors.textOnAccent : fg;

  return (
    <Pressable
      testID={testID}
      onPress={onPress}
      disabled={inert}
      accessible
      accessibilityRole="button"
      accessibilityLabel={accessibilityLabel}
      accessibilityHint={accessibilityHint}
      accessibilityState={{ disabled: inert, busy }}
      // مساحة اللمس لا تقل عن 44pt مهما صغر النص.
      hitSlop={8}
      style={({ pressed }) => ({
        minHeight: MIN_TOUCH_TARGET,
        borderRadius: theme.radii.md,
        borderWidth: kind === 'quiet' ? 1 : 0,
        borderColor: border,
        backgroundColor: background,
        opacity: inert ? 0.45 : pressed ? 0.82 : 1,
        alignItems: 'center',
        justifyContent: 'center',
        paddingHorizontal: theme.spacing.xl,
        paddingVertical: theme.spacing.md,
        flexDirection: 'row',
        gap: theme.spacing.sm,
      })}
    >
      {busy ? <ActivityIndicator size="small" color={labelColor} /> : null}
      <Text variant="bodyStrong" style={{ color: labelColor }} align="center">
        {busy ? t.emergency.sending : label}
      </Text>
    </Pressable>
  );
}

interface ConfirmButtonProps extends Omit<ButtonProps, 'onPress'> {
  /** نصّ التأكيد الذي يظهر قبل التنفيذ. */
  confirmTitle: string;
  confirmBody: string;
  confirmLabel: string;
  onConfirm: () => void;
}

/**
 * زر بخطوتين للإجراءات التي لا رجعة فيها من الهاتف.
 *
 * التأكيد **داخل الشاشة** لا في تنبيه نظام: التنبيه يُقرأ بسرعة ويُضغط بلا وعي،
 * والبطاقة تُظهر الأثر كاملاً قبل الضغط.
 */
export function ConfirmButton({
  label,
  confirmTitle,
  confirmBody,
  confirmLabel,
  onConfirm,
  accessibilityLabel,
  accessibilityHint,
  tone = 'negative',
  disabled = false,
  busy = false,
  testID,
}: ConfirmButtonProps): React.JSX.Element {
  const theme = useTheme();
  const [armed, setArmed] = useState(false);
  const { fg, bg } = toneOf(theme.colors, tone);

  if (!armed) {
    return (
      <Button
        label={label}
        kind="secondary"
        tone={tone}
        disabled={disabled}
        busy={busy}
        accessibilityLabel={accessibilityLabel}
        accessibilityHint={accessibilityHint}
        testID={testID}
        onPress={() => {
          setArmed(true);
        }}
      />
    );
  }

  return (
    <View
      testID={`${testID ?? 'confirm'}-panel`}
      style={{
        backgroundColor: bg,
        borderColor: fg,
        borderWidth: 1,
        borderRadius: theme.radii.md,
        padding: theme.spacing.lg,
        gap: theme.spacing.md,
      }}
    >
      <Text variant="bodyStrong" style={{ color: fg }} accessibilityRole="header">
        {confirmTitle}
      </Text>
      <Text variant="caption" tone="secondary">
        {confirmBody}
      </Text>
      <View style={{ flexDirection: 'row', gap: theme.spacing.md }}>
        <View style={{ flex: 1 }}>
          <Button
            label={t.common.cancel}
            kind="quiet"
            tone="neutral"
            accessibilityLabel={`${t.common.cancel} — ${confirmTitle}`}
            testID={`${testID ?? 'confirm'}-cancel`}
            onPress={() => {
              setArmed(false);
            }}
          />
        </View>
        <View style={{ flex: 1 }}>
          <Button
            label={confirmLabel}
            kind="primary"
            tone={tone}
            busy={busy}
            accessibilityLabel={confirmLabel}
            accessibilityHint={confirmBody}
            testID={`${testID ?? 'confirm'}-accept`}
            onPress={() => {
              setArmed(false);
              onConfirm();
            }}
          />
        </View>
      </View>
    </View>
  );
}
