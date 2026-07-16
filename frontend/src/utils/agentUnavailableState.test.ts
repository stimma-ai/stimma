import assert from 'node:assert/strict'
import test from 'node:test'
import { resolveAgentUnavailableState } from './agentUnavailableState.ts'

test('signed out is the generic unavailable case; no-balance requires auth', () => {
  assert.equal(resolveAgentUnavailableState({ isAuthenticated: false }), 'unavailable')
  assert.equal(resolveAgentUnavailableState({ isAuthenticated: false, cloudCredits: 0 }), 'unavailable')
  assert.equal(resolveAgentUnavailableState({ isAuthenticated: true, cloudCredits: 0 }), 'no-balance')
  assert.equal(resolveAgentUnavailableState({ isAuthenticated: true, cloudCredits: '0' }), 'no-balance')
})

test('recognizes provider entitlement errors when account data is not loaded', () => {
  assert.equal(resolveAgentUnavailableState({
    isAuthenticated: true,
    cloudStatus: 'subscription_required',
  }), 'no-balance')
})

test('keeps privacy lockdown and unrelated cloud failures distinct', () => {
  assert.equal(resolveAgentUnavailableState({
    privacyLockdownActive: true,
    isAuthenticated: true,
    cloudCredits: 0,
  }), 'privacy')
  assert.equal(resolveAgentUnavailableState({
    isAuthenticated: true,
    cloudCredits: 100,
    cloudStatus: 'cloud_unreachable',
  }), 'unavailable')
})
