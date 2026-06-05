# Claude Code Notes

## Development Server

The demo dev server is already running on **port 5173** with hot reload enabled.

- Demo URL: http://localhost:5173
- Do NOT try to start the dev server - it's already running
- Changes to library code auto-rebuild and hot reload

## Project Structure

- `/src` - Main library source code
- `/demo` - Demo application
- `/dist` - Built library output

## Build Commands

```bash
# Build library (run from root)
npm run build

# Demo is already running, no need to start it
```

## Key Files

- `src/components/StimmaEditor.vue` - Main editor component
- `src/composables/useEditor.ts` - Editor state management
- `src/composables/useHistory.ts` - Undo/redo history
- `src/utils/serialization.ts` - Save/load project serialization
- `demo/src/App.vue` - Demo application
