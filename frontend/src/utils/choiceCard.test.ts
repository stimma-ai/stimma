import test from 'node:test'
import assert from 'node:assert/strict'
import { ref } from 'vue'
import { createChoiceCard } from './choiceCard.ts'

const el = { getBoundingClientRect: () => ({ top: 1, left: 2 }) } as unknown as Element

test('a card opens only on a choice that is shown', () => {
  const byId = ref<Record<string, unknown>>({ hair: {} })
  const card = createChoiceCard(byId)
  card.open('hidden-lora-choice', el)
  assert.equal(card.openCard.value, null)
  card.open(null, el)
  assert.equal(card.openCard.value, null)
  card.open('hair', null)
  assert.equal(card.openCard.value, null)
  card.open('hair', el)
  assert.equal(card.openCard.value?.id, 'hair')
})

test('the card closes when its choice goes, and stays open when it stays', () => {
  const byId = ref<Record<string, unknown>>({ hair: {}, coat: {} })
  const card = createChoiceCard(byId)
  card.open('hair', el)
  byId.value = { hair: {}, shoes: {} }  // a new prepare that still has it
  assert.equal(card.openCard.value?.id, 'hair')
  byId.value = { shoes: {} }  // one that doesn't
  assert.equal(card.openCard.value, null)
  card.open('shoes', el)
  card.close()
  assert.equal(card.openCard.value, null)
})
