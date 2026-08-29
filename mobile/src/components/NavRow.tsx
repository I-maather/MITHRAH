import React from 'react';
import { Pressable, View } from 'react-native';
import { useRouter, type Href } from 'expo-router';

import { useSession } from '@/auth/SessionProvider';
import { MIN_TOUCH_TARGET, useTheme } from '@/theme';
import { Text } from './Text';
import { StatusPill } from './StatusPill';
import type { ToneName } from '@/theme';

interface NavRowProps {
  label: string;
  hint?: string;
  href: Href;
  /** شارة على يسار الصف: حالة مختصرة. */
  badge?: string;
  badgeTone?: ToneName;
  testID?: string;
}

/**
 * صف انتقال. الوجهة **داخلية فقط** — لا يفتح هذا الصف رابطاً خارجياً أبداً.
 */
export function NavRow({
  label,
  hint,
  href,
  badge,
  badgeTone = 'neutral',
  testID,
}: NavRowProps): React.JSX.Element {
  const theme = useTheme();
  const router = useRouter();
  const { registerActivity } = useSession();

  return (
    <Pressable
      testID={testID}
      accessible
      accessibilityRole="link"
      accessibilityLabel={hint === undefined ? label : `${label}. ${hint}`}
      accessibilityHint="يفتح الشاشة"
      onPress={() => {
        registerActivity();
        router.push(href);
      }}
      style={({ pressed }) => ({
        minHeight: MIN_TOUCH_TARGET,
        flexDirection: 'row',
        alignItems: 'center',
        justifyContent: 'space-between',
        gap: theme.spacing.md,
        paddingVertical: theme.spacing.md,
        paddingHorizontal: theme.spacing.lg,
        borderRadius: theme.radii.md,
        backgroundColor: pressed ? theme.colors.surfaceSunken : 'transparent',
      })}
    >
      <View style={{ flexShrink: 1, gap: 2 }}>
        <Text variant="bodyStrong">{label}</Text>
        {hint !== undefined ? (
          <Text variant="caption" tone="secondary">
            {hint}
          </Text>
        ) : null}
      </View>
      {badge !== undefined ? <StatusPill label={badge} tone={badgeTone} /> : null}
    </Pressable>
  );
}
