/**
 * Where everything a client persists belongs.
 *
 * The line: what you're working on, and how you like your tools to behave,
 * follows you and lives on the server. What this screen and hardware are like,
 * and where this client is looking right now, stays with the device.
 *
 * A test (tests/stateRegistry.test.mjs) fails on any storage key not declared
 * here, so adding one means deciding which side of the line it's on.
 */

/** Shared documents whose local value a client carries over the first time. */
const MIGRATED: RegExp[] = [
  /^tool_.+__i_[^_]+_(state|active_preset|collapsed_groups|ai_prompt_expanded|ui|video_images|remix)$/,
  /^lorapool_.+$/,
  /^tool_auto_delete_duration$/,
  /^lora_show_raw$/,
  /^controlnet_.+$/,
  /^frame-mode_.+$/,
  /^global_search_recents$/,
  /^model_picker_recent$/,
  /^chat_.+_draft$/,
  /^flow_.+_program_draft$/,
  /^flow_code_intro_seen$/,
  /^imageEditor_toolPrefs$/,
  /^imageEditor_colorPicker_recents$/,
  /^svg-viewer_background$/,
  /^media_picker_recent_inputs$/,
  /^media_picker_recent_picks_.+$/,
  /^remix_recent$/,
  /^send-to-tool_.+_recent$/,
  /^generate-more_recent$/,
  /^onboarding_completed$/,
  /^providerManager_hintDismissed$/,
  /^dismissed_warning_.+$/,
]

/** Large values a client carries over, stored as files on the server. */
const MIGRATED_BLOB = /^tool_.+__i_[^_]+_(mask|paint_\d+)$/

export function isMigratedKey(docKey: string): boolean {
  return MIGRATED.some(pattern => pattern.test(docKey))
}

export function isMigratedBlobKey(docKey: string): boolean {
  return MIGRATED_BLOB.test(docKey)
}

/**
 * The tool tab a tool-scoped key belongs to, or null. A tool tab's data only
 * moves with the tab; anything left by a closed tab stays behind.
 */
export function instanceOfKey(docKey: string): string | null {
  const match = docKey.match(/__i_([0-9A-Za-z]+)(?![0-9A-Za-z-])/)
  return match ? match[1] : null
}

/**
 * Every key, by its leading literal part (what a make*Key call or raw storage
 * call names in the source).
 */
export const STATE_REGISTRY = {
  /** Lives on the server, shared by every client of the profile. */
  shared: [
    'workspace_tabs', 'tool', 'lorapool', 'tool_auto_delete_duration', 'lora', 'controlnet', 'frame-mode',
    'global_search', 'model_picker', 'chat:draft', 'flow:program_draft', 'flow:code_intro_seen',
    'imageEditor:toolPrefs', 'imageEditor:colorPicker:recents', 'svg-viewer', 'media_picker', 'remix',
    'send-to-tool', 'generate-more', 'onboarding_completed', 'providerManager', 'dismissed_warning',
    'mask_editor:brush_size', 'mask_editor:expand_percent', 'folder_picker_recents', 'sprite-player', 'recent', 'ui', 'contact-sheet',
    'chat_dock', 'quick_ask',
  ],
  /** Stays with this client. */
  device: [
    'workspace_tabs:last_library_route', 'working_context', 'last_route', 'project', 'sidebar', 'allTools',
    'browse', 'trash', 'filters', 'grid_scroll', 'chat:artifact_stage_state', 'chat:artifact_chat_width', 'chatSettingsPanelVisible', 'home_draft',
    'flow:chat_panel_open', 'flow:chat_panel_width', 'flow_graph', 'flow.viewMode', 'flow.graphCollapseForeach', 'stimma:flow-code-monospace',
    'imageEditor:colorPicker:tab', 'stimma_editor_sidebar', 'stimma_editor_properties', 'stimma:vim-mode',
    'stimma:vim-commands', 'stimma:monospace-font', 'slideshow', 'media_playback', 'stimma:export-last-folder',
    'stimma:export-combine-zip', 'stimma:export-bundle-as', 'terms_accepted', 'stimma_device_coachmark_seen',
    'browser_guid', 'pin_cache', 'profileId', 'stimma_bundle_id', 'stimma_sandbox', 'server_update_operation',
    'theme', 'stimma_install_theme', 'stimma_hide_prices', 'stimma_hide_account', 'stimma:flags', 'stimma-viewport-override',
    'mask_editor:editor_height', 'media_picker_popover', 'stimma-roomy-agent-docked', 'workspace_outbox',
    'workspace_migrated', 'workspace_blobs_migrated', 'workspace_client_id', 'tool:pending_input',
    'tool:pending_generation', 'tool:pending_generation_mask',
  ],
  /** Names in the server's user_preferences, which was never client storage. */
  serverPreference: [
    'app_updates_policy', 'app_updates_skip_version', 'app_updates_last_checked_at', 'release_notes_last_seen',
  ],
} as const
