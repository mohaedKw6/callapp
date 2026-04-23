import React from 'react';
import { View, Text, Pressable, StyleSheet } from 'react-native';
import * as Haptics from 'expo-haptics';
import { Colors, Radii } from '../theme/colors';

interface Props {
  onPress: (digit: string) => void;
  onDelete: () => void;
  onLongDelete: () => void;
}

const KEYS: Array<{ d: string; sub?: string }> = [
  { d: '1', sub: ' ' },
  { d: '2', sub: 'ABC' },
  { d: '3', sub: 'DEF' },
  { d: '4', sub: 'GHI' },
  { d: '5', sub: 'JKL' },
  { d: '6', sub: 'MNO' },
  { d: '7', sub: 'PQRS' },
  { d: '8', sub: 'TUV' },
  { d: '9', sub: 'WXYZ' },
  { d: '*', sub: '' },
  { d: '0', sub: '+' },
  { d: '#', sub: '' },
];

export default function Numpad({ onPress, onDelete, onLongDelete }: Props) {
  const tap = (d: string) => {
    Haptics.selectionAsync();
    onPress(d);
  };
  return (
    <View style={S.grid}>
      {KEYS.map((k) => (
        <Pressable
          key={k.d}
          style={({ pressed }) => [S.key, pressed && S.keyPressed]}
          onPress={() => tap(k.d)}
          onLongPress={() => k.d === '0' && tap('+')}
        >
          <Text style={S.digit}>{k.d}</Text>
          {k.sub ? <Text style={S.sub}>{k.sub}</Text> : <View style={S.subSpace} />}
        </Pressable>
      ))}
    </View>
  );
}

export function DeleteKey({ onPress, onLongPress }: { onPress: () => void; onLongPress: () => void }) {
  return (
    <Pressable
      onPress={() => { Haptics.selectionAsync(); onPress(); }}
      onLongPress={onLongPress}
      hitSlop={12}
      style={S.del}
    >
      <Text style={S.delTxt}>⌫</Text>
    </Pressable>
  );
}

const S = StyleSheet.create({
  grid: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    justifyContent: 'center',
    paddingHorizontal: 24,
    gap: 14,
  },
  key: {
    width: 78,
    height: 78,
    borderRadius: Radii.full,
    backgroundColor: Colors.bgElevated,
    justifyContent: 'center',
    alignItems: 'center',
    borderWidth: 1,
    borderColor: Colors.borderSoft,
  },
  keyPressed: {
    backgroundColor: Colors.card,
    transform: [{ scale: 0.94 }],
  },
  digit: { color: Colors.text, fontSize: 30, fontWeight: '500', lineHeight: 32 },
  sub: { color: Colors.textDim, fontSize: 10, fontWeight: '700', letterSpacing: 1.5, marginTop: 2 },
  subSpace: { height: 12, marginTop: 2 },
  del: { padding: 18 },
  delTxt: { color: Colors.textMuted, fontSize: 24 },
});
