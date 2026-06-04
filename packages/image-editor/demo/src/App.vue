<script setup lang="ts">
import { ref, computed, onMounted } from 'vue';
import {
  StimmaEditor,
  cropPlugin,
  finetunePlugin,
  filterPlugin,
  effectsPlugin,
  annotatePlugin,
  retouchPlugin,
  type LoadResult,
  type ProcessResult,
  type SerializedProject,
} from '@stimma/image-editor';

// Types for saved projects in localStorage
interface SavedProject {
  id: string;
  name: string;
  thumbnailDataUrl?: string;
  createdAt: number;
  updatedAt: number;
}

// LocalStorage key
const STORAGE_KEY = 'stimma-editor-projects';
const PROJECT_PREFIX = 'stimma-project-';

// Sample images
const sampleImages = [
  {
    name: 'Landscape',
    url: 'https://images.unsplash.com/photo-1506905925346-21bda4d32df4?w=1200',
  },
  {
    name: 'Portrait',
    url: 'https://images.unsplash.com/photo-1544005313-94ddf0286df2?w=800',
  },
  {
    name: 'Square',
    url: 'https://images.unsplash.com/photo-1518791841217-8f162f1e1131?w=800',
  },
];

// State
const selectedImage = ref<string | null>(null);
const showEditor = ref(false);
const theme = ref<'light' | 'dark'>((localStorage.getItem('stimma-demo-theme') as 'light' | 'dark') || 'dark');
const exportedImage = ref<string | null>(null);
const exportedSize = ref<{ width: number; height: number } | null>(null);
const editorRef = ref<InstanceType<typeof StimmaEditor> | null>(null);
const savedProjects = ref<SavedProject[]>([]);
const currentProjectId = ref<string | null>(null);
const projectName = ref('Untitled Project');
const showSaveDialog = ref(false);
const isSaving = ref(false);

// Plugins
const plugins = [cropPlugin, retouchPlugin, finetunePlugin, filterPlugin, effectsPlugin, annotatePlugin];

// Load saved projects from localStorage on mount
onMounted(() => {
  loadProjectList();
});

function loadProjectList() {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored) {
      savedProjects.value = JSON.parse(stored);
    }
  } catch (e) {
    console.error('Failed to load project list:', e);
  }
}

function saveProjectList() {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(savedProjects.value));
  } catch (e) {
    console.error('Failed to save project list:', e);
  }
}

function generateProjectId(): string {
  return `${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;
}

// Handlers
function selectImage(url: string) {
  selectedImage.value = url;
  showEditor.value = true;
  exportedImage.value = null;
  currentProjectId.value = null;
  projectName.value = 'Untitled Project';
}

function handleFileUpload(event: Event) {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0];
  if (file) {
    const url = URL.createObjectURL(file);
    selectedImage.value = url;
    showEditor.value = true;
    exportedImage.value = null;
    currentProjectId.value = null;
    projectName.value = file.name.replace(/\.[^.]+$/, '');
  }
}

function handleLoad(result: LoadResult) {
  console.log('Image loaded:', result);
}

function handleProcess(result: ProcessResult) {
  console.log('Image processed:', result);
  exportedImage.value = URL.createObjectURL(result.dest);
  exportedSize.value = result.imageSize;
  showEditor.value = false;
}

function handleClose() {
  showEditor.value = false;
}

async function handleDone() {
  if (!editorRef.value) return;
  try {
    const result = await editorRef.value.processImage();
    handleProcess(result);
  } catch (e) {
    console.error('Failed to process image:', e);
  }
}

function downloadImage() {
  if (exportedImage.value) {
    const a = document.createElement('a');
    a.href = exportedImage.value;
    a.download = 'edited-image.jpg';
    a.click();
  }
}

function toggleTheme() {
  theme.value = theme.value === 'light' ? 'dark' : 'light';
  localStorage.setItem('stimma-demo-theme', theme.value);
}

// Save project to localStorage
async function saveProject() {
  if (!editorRef.value) return;

  isSaving.value = true;
  try {
    const serialized = await editorRef.value.serialize({
      name: projectName.value,
      includeThumbnail: true,
      thumbnailMaxSize: 200,
    });

    // Generate or use existing ID
    const id = currentProjectId.value || generateProjectId();
    currentProjectId.value = id;

    // Save the full project data
    localStorage.setItem(PROJECT_PREFIX + id, JSON.stringify(serialized));

    // Update project list
    const existingIndex = savedProjects.value.findIndex(p => p.id === id);
    const projectMeta: SavedProject = {
      id,
      name: projectName.value,
      thumbnailDataUrl: serialized.thumbnailDataUrl,
      createdAt: existingIndex >= 0 ? savedProjects.value[existingIndex].createdAt : Date.now(),
      updatedAt: Date.now(),
    };

    if (existingIndex >= 0) {
      savedProjects.value[existingIndex] = projectMeta;
    } else {
      savedProjects.value.unshift(projectMeta);
    }

    saveProjectList();
    showSaveDialog.value = false;

    console.log('Project saved:', id);
  } catch (e) {
    console.error('Failed to save project:', e);
    alert('Failed to save project: ' + (e as Error).message);
  } finally {
    isSaving.value = false;
  }
}

// Load project from localStorage
async function openProject(project: SavedProject) {
  try {
    const stored = localStorage.getItem(PROJECT_PREFIX + project.id);
    if (!stored) {
      alert('Project not found');
      return;
    }

    const serialized: SerializedProject = JSON.parse(stored);

    // We need to open the editor first, then load the project
    selectedImage.value = serialized.imageDataUrl;
    currentProjectId.value = project.id;
    projectName.value = project.name;
    showEditor.value = true;
    exportedImage.value = null;

    // Wait for editor to mount and load the image
    // Then load the full project state
    setTimeout(async () => {
      if (editorRef.value) {
        await editorRef.value.loadProject(serialized);
        console.log('Project loaded:', project.id);
      }
    }, 500);
  } catch (e) {
    console.error('Failed to load project:', e);
    alert('Failed to load project: ' + (e as Error).message);
  }
}

// Delete project from localStorage
function deleteProject(project: SavedProject, event: Event) {
  event.stopPropagation();

  if (!confirm(`Delete "${project.name}"?`)) return;

  try {
    localStorage.removeItem(PROJECT_PREFIX + project.id);
    savedProjects.value = savedProjects.value.filter(p => p.id !== project.id);
    saveProjectList();

    if (currentProjectId.value === project.id) {
      currentProjectId.value = null;
    }
  } catch (e) {
    console.error('Failed to delete project:', e);
  }
}

// Export rasterized image
async function exportRasterized() {
  if (!editorRef.value) return;

  try {
    const result = await editorRef.value.rasterize({
      format: 'image/png',
      quality: 1,
    });

    // Download the rasterized image
    const url = URL.createObjectURL(result.dest);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${projectName.value || 'export'}.png`;
    a.click();
    URL.revokeObjectURL(url);
  } catch (e) {
    console.error('Failed to export:', e);
    alert('Failed to export: ' + (e as Error).message);
  }
}

// Format date for display
function formatDate(timestamp: number): string {
  return new Date(timestamp).toLocaleDateString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}
</script>

<template>
  <div
    class="bg-gray-100"
    :class="[
      theme === 'dark' ? 'dark bg-stimma-bg' : '',
      showEditor ? 'h-screen flex flex-col' : 'min-h-full'
    ]"
  >
    <!-- Header -->
    <header class="bg-white dark:bg-stimma-surface shadow-sm">
      <div class="max-w-6xl mx-auto px-4 py-4 flex items-center justify-between">
        <h1 class="text-xl font-semibold text-gray-900 dark:text-white">
          Stimma Image Editor Demo
        </h1>
        <div class="flex items-center gap-3">
          <!-- Save button when editor is open -->
          <button
            v-if="showEditor"
            class="px-3 py-1.5 text-sm rounded-md bg-blue-500 text-white hover:bg-blue-600 transition-colors"
            @click="showSaveDialog = true"
          >
            Save Project
          </button>
          <button
            v-if="showEditor"
            class="px-3 py-1.5 text-sm rounded-md bg-green-500 text-white hover:bg-green-600 transition-colors"
            @click="exportRasterized"
          >
            Export PNG
          </button>
          <button
            class="p-2 rounded-md bg-gray-100 dark:bg-stimma-surface text-gray-700 dark:text-gray-200 hover:bg-gray-200 dark:hover:bg-gray-600 transition-colors"
            @click="toggleTheme"
            :title="theme === 'light' ? 'Switch to dark mode' : 'Switch to light mode'"
          >
            <!-- Sun icon (shown in dark mode) -->
            <svg v-if="theme === 'dark'" class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 3v1m0 16v1m9-9h-1M4 12H3m15.364 6.364l-.707-.707M6.343 6.343l-.707-.707m12.728 0l-.707.707M6.343 17.657l-.707.707M16 12a4 4 0 11-8 0 4 4 0 018 0z" />
            </svg>
            <!-- Moon icon (shown in light mode) -->
            <svg v-else class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M20.354 15.354A9 9 0 018.646 3.646 9.003 9.003 0 0012 21a9.003 9.003 0 008.354-5.646z" />
            </svg>
          </button>
        </div>
      </div>
    </header>

    <!-- Main content -->
    <main :class="showEditor ? 'flex-1 min-h-0' : 'max-w-6xl mx-auto px-4 py-8'">
      <!-- Image selector / Project list -->
      <section v-if="!showEditor" class="mb-8">
        <!-- Saved Projects -->
        <div v-if="savedProjects.length > 0" class="mb-8">
          <h2 class="text-lg font-medium text-gray-900 dark:text-white mb-4">
            Saved Projects
          </h2>
          <div class="grid grid-cols-4 gap-4">
            <button
              v-for="project in savedProjects"
              :key="project.id"
              class="relative group aspect-video rounded-lg overflow-hidden bg-gray-200 dark:bg-stimma-surface hover:ring-2 hover:ring-blue-500 transition-all focus:outline-none focus:ring-2 focus:ring-blue-500"
              @click="openProject(project)"
            >
              <img
                v-if="project.thumbnailDataUrl"
                :src="project.thumbnailDataUrl"
                :alt="project.name"
                class="w-full h-full object-cover"
              />
              <div
                v-else
                class="w-full h-full flex items-center justify-center text-gray-400"
              >
                No preview
              </div>
              <!-- Overlay with project info -->
              <div
                class="absolute inset-0 bg-gradient-to-t from-black/70 to-transparent opacity-0 group-hover:opacity-100 transition-opacity flex flex-col justify-end p-2"
              >
                <div class="text-white text-sm font-medium truncate">
                  {{ project.name }}
                </div>
                <div class="text-white/70 text-xs">
                  {{ formatDate(project.updatedAt) }}
                </div>
              </div>
              <!-- Delete button -->
              <button
                class="absolute top-2 right-2 w-6 h-6 rounded-full bg-red-500 text-white opacity-0 group-hover:opacity-100 transition-opacity hover:bg-red-600 flex items-center justify-center text-sm"
                @click="deleteProject(project, $event)"
              >
                &times;
              </button>
            </button>
          </div>
        </div>

        <h2 class="text-lg font-medium text-gray-900 dark:text-white mb-4">
          Start with a new image
        </h2>

        <!-- Sample images -->
        <div class="grid grid-cols-3 gap-4 mb-6">
          <button
            v-for="sample in sampleImages"
            :key="sample.name"
            class="aspect-video rounded-lg overflow-hidden bg-gray-200 dark:bg-stimma-surface hover:ring-2 hover:ring-blue-500 transition-all focus:outline-none focus:ring-2 focus:ring-blue-500"
            @click="selectImage(sample.url)"
          >
            <img
              :src="sample.url"
              :alt="sample.name"
              class="w-full h-full object-cover"
            />
          </button>
        </div>

        <!-- Upload -->
        <div class="flex items-center gap-4">
          <label
            class="px-4 py-2 bg-blue-500 text-white rounded-md hover:bg-blue-600 cursor-pointer transition-colors"
          >
            Upload Image
            <input
              type="file"
              accept="image/*"
              class="hidden"
              @change="handleFileUpload"
            />
          </label>
          <span class="text-sm text-gray-500 dark:text-gray-400">
            or select a sample image above
          </span>
        </div>
      </section>

      <!-- Editor -->
      <section v-if="showEditor && selectedImage" class="h-full overflow-hidden">
        <StimmaEditor
          ref="editorRef"
          :src="selectedImage"
          :plugins="plugins"
          :theme="theme"
          @load="handleLoad"
          @process="handleProcess"
        >
          <template #toolbar-end>
            <button
              class="stimma-toolbar__button"
              title="Close"
              @click="handleClose"
            >
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M18 6L6 18M6 6l12 12" />
              </svg>
            </button>
            <button
              class="stimma-toolbar__button stimma-toolbar__button--primary"
              style="gap: 6px"
              @click="handleDone"
            >
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M20 6L9 17l-5-5" />
              </svg>
              <span>Done</span>
            </button>
          </template>
        </StimmaEditor>
      </section>

      <!-- Export preview -->
      <section v-if="exportedImage" class="mt-8">
        <h2 class="text-lg font-medium text-gray-900 dark:text-white mb-4">
          Exported Image
        </h2>
        <div class="flex gap-6">
          <div class="flex-shrink-0">
            <img
              :src="exportedImage"
              alt="Exported"
              class="max-w-md rounded-lg shadow-md"
            />
          </div>
          <div class="flex flex-col gap-4">
            <div class="text-sm text-gray-600 dark:text-gray-300">
              <p><strong>Dimensions:</strong> {{ exportedSize?.width }} x {{ exportedSize?.height }}</p>
            </div>
            <div class="flex gap-2">
              <button
                class="px-4 py-2 bg-blue-500 text-white rounded-md hover:bg-blue-600 transition-colors"
                @click="downloadImage"
              >
                Download
              </button>
              <button
                class="px-4 py-2 border border-gray-300 dark:border-gray-600 bg-white dark:bg-stimma-surface text-gray-700 dark:text-gray-200 rounded-md hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors"
                @click="showEditor = true"
              >
                Edit Again
              </button>
            </div>
          </div>
        </div>
      </section>
    </main>

    <!-- Save Dialog -->
    <div
      v-if="showSaveDialog"
      class="fixed inset-0 bg-black/50 flex items-center justify-center z-50"
      :class="{ dark: theme === 'dark' }"
      @click.self="showSaveDialog = false"
    >
      <div class="bg-white dark:bg-stimma-surface rounded-lg shadow-xl p-6 w-96">
        <h3 class="text-lg font-medium text-gray-900 dark:text-white mb-4">
          Save Project
        </h3>
        <div class="mb-4">
          <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
            Project Name
          </label>
          <input
            v-model="projectName"
            type="text"
            class="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-md bg-white dark:bg-neutral-800 text-gray-900 dark:text-white focus:ring-2 focus:ring-blue-500 focus:border-transparent"
            placeholder="Enter project name"
            @keyup.enter="saveProject"
          />
        </div>
        <div class="flex justify-end gap-2">
          <button
            class="px-4 py-2 text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700 rounded-md transition-colors"
            @click="showSaveDialog = false"
          >
            Cancel
          </button>
          <button
            class="px-4 py-2 bg-blue-500 text-white rounded-md hover:bg-blue-600 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            :disabled="isSaving || !projectName.trim()"
            @click="saveProject"
          >
            {{ isSaving ? 'Saving...' : 'Save' }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>
