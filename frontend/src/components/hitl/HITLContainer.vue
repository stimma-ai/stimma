<template>
  <div class="hitl-container bg-surface-raised shadow rounded-lg p-4 min-w-[420px]">
    <!-- Render appropriate component based on action type -->
    <RetryPrompt
      v-if="action.type === 'retry'"
      :prompt="action.prompt"
      :error-message="action.error_message"
      :error-summary="action.error_summary"
      :failed-node-id="action.failed_node_id"
      @respond="handleRetryResponse"
    />

    <PlanApproval
      v-else-if="action.type === 'plan_approval'"
      :prompt="action.prompt"
      :plan-data="action.plan_data"
      :show-plan="false"
      @respond="handlePlanApprovalResponse"
    />

    <ToolPermissionPrompt
      v-else-if="action.type === 'request_tool_permission'"
      :prompt="action.prompt"
      :task-type="action.task_type"
      :suggested-tool-id="action.suggested_tool_id"
      :reason="action.reason"
      @respond="handleToolPermissionResponse"
    />

    <V2PermissionPrompt
      v-else-if="action.type === 'v2_tool_permission'"
      :action="action"
      :completed="localResolved != null"
      :response="localResolved"
      @respond="handleV2PermissionResponse"
    />

    <AskUserPrompt
      v-else-if="action.type === 'ask_user'"
      :action="action"
      :completed="localResolved != null"
      :response="localResolved"
      @respond="handleAskUserResponse"
    />

    <div v-else class="text-red-500">
      Unknown HITL action type: {{ action.type }}
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import RetryPrompt from './RetryPrompt.vue'
import PlanApproval from './PlanApproval.vue'
import ToolPermissionPrompt from './ToolPermissionPrompt.vue'
import V2PermissionPrompt from './V2PermissionPrompt.vue'
import AskUserPrompt from './AskUserPrompt.vue'
import { getCurrentProfileId } from '../../composables/useProfile'

const props = defineProps({
  chatId: {
    type: Number,
    required: true
  },
  action: {
    type: Object,
    required: true
  }
})

const emit = defineEmits(['responded'])

const isSubmitting = ref(false)
const localResolved = ref(null)

async function submitResponse(responseData) {
  if (isSubmitting.value) return
  isSubmitting.value = true

  try {
    const response = await fetch(`/api/chats/${props.chatId}/human-response`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Profile-ID': getCurrentProfileId()
      },
      body: JSON.stringify(responseData)
    })

    if (!response.ok) {
      const error = await response.text()
      console.error('HITL response failed:', error)
      return
    }

    emit('responded')
  } catch (error) {
    console.error('Error submitting HITL response:', error)
  } finally {
    isSubmitting.value = false
  }
}

function handleRetryResponse(response) {
  submitResponse(response)
}

function handlePlanApprovalResponse(response) {
  submitResponse(response)
}

function handleToolPermissionResponse(response) {
  submitResponse(response)
}

function handleV2PermissionResponse(response) {
  // Immediately show resolved state
  localResolved.value = response
  submitResponse(response)
}

function handleAskUserResponse(response) {
  localResolved.value = response
  submitResponse(response)
}
</script>

<style scoped>
.hitl-container {
  animation: fadeIn 0.2s ease-out;
}

@keyframes fadeIn {
  from {
    opacity: 0;
    transform: translateY(4px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}
</style>
