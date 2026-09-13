// Shared read-only and flow editor syntax palette.
import { HighlightStyle } from '@codemirror/language'
import { tags as t } from '@lezer/highlight'

export const darkHighlightStyle = HighlightStyle.define([
  { tag: t.comment, color: '#6b7d8a', fontStyle: 'italic' },
  { tag: [t.keyword, t.modifier, t.controlKeyword, t.operatorKeyword, t.definitionKeyword], color: '#c792ea' },
  { tag: [t.string, t.special(t.string)], color: '#ecc48d' },
  { tag: [t.number, t.bool, t.null, t.atom], color: '#f78c6c' },
  { tag: [t.function(t.variableName), t.function(t.definition(t.variableName))], color: '#82aaff' },
  { tag: [t.definition(t.variableName), t.definition(t.propertyName)], color: '#d6deeb' },
  { tag: t.variableName, color: '#d6deeb' },
  { tag: t.propertyName, color: '#7fdbca' },
  { tag: [t.className, t.typeName], color: '#ffcb6b' },
  { tag: t.meta, color: '#82aaff' },
  { tag: [t.operator, t.punctuation, t.bracket, t.separator], color: '#89ddff' },
  { tag: t.regexp, color: '#5ca7e4' },
  { tag: t.escape, color: '#f78c6c' },
  { tag: t.invalid, color: '#ff5874' },
])

export const lightHighlightStyle = HighlightStyle.define([
  { tag: t.comment, color: '#6a737d', fontStyle: 'italic' },
  { tag: [t.keyword, t.modifier, t.controlKeyword, t.operatorKeyword, t.definitionKeyword], color: '#a626a4' },
  { tag: [t.string, t.special(t.string)], color: '#50a14f' },
  { tag: [t.number, t.bool, t.null, t.atom], color: '#986801' },
  { tag: [t.function(t.variableName), t.function(t.definition(t.variableName))], color: '#4078f2' },
  { tag: [t.definition(t.variableName), t.definition(t.propertyName)], color: '#383a42' },
  { tag: t.variableName, color: '#383a42' },
  { tag: t.propertyName, color: '#0184bc' },
  { tag: [t.className, t.typeName], color: '#c18401' },
  { tag: t.meta, color: '#4078f2' },
  { tag: [t.operator, t.punctuation, t.bracket, t.separator], color: '#0184bc' },
  { tag: t.regexp, color: '#0184bc' },
  { tag: t.escape, color: '#986801' },
  { tag: t.invalid, color: '#e45649' },
])
