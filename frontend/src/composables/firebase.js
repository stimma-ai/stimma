/**
 * Firebase initialization and auth exports.
 */
import { initializeApp } from 'firebase/app'
import {
  getAuth,
  signInWithCustomToken,
  signOut as firebaseSignOut,
  onAuthStateChanged,
} from 'firebase/auth'

const firebaseConfig = {
  apiKey: 'AIzaSyB4xzVbmK5OnZGfs9qSwGJdPVbBoddYCvw',
  authDomain: 'stimma-13a84.firebaseapp.com',
  projectId: 'stimma-13a84',
  storageBucket: 'stimma-13a84.firebasestorage.app',
  messagingSenderId: '488046825601',
  appId: '1:488046825601:web:3d124378cd6017f2ebbd80',
}

const app = initializeApp(firebaseConfig)
const auth = getAuth(app)

export {
  auth,
  signInWithCustomToken,
  firebaseSignOut,
  onAuthStateChanged,
}
