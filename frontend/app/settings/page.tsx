'use client'

import { useEffect, useState } from 'react'
import { fetchSettings, updateSettings } from '@/lib/api'

const USER_ID = 'test-user-1'

interface Settings {
  wake_up_time: string
  workout_duration_minutes: number
  workout_preference: string
  commute_buffer_minutes: number
  preferred_messaging_channel: string
  google_calendar_enabled: boolean
  apple_ical_enabled: boolean
}

export default function Settings() {
  const [settings, setSettings] = useState<Settings | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [message, setMessage] = useState('')

  useEffect(() => {
    fetchData()
  }, [])

  const fetchData = async () => {
    try {
      const result = await fetchSettings(USER_ID)
      setSettings(result.settings)
    } catch (err) {
      console.error('Failed to fetch settings:', err)
    } finally {
      setLoading(false)
    }
  }

  const handleSave = async () => {
    if (!settings) return

    setSaving(true)
    setMessage('')

    try {
      await updateSettings(USER_ID, settings)
      setMessage('✓ Settings saved')
      setTimeout(() => setMessage(''), 2000)
    } catch (err) {
      console.error('Failed to save settings:', err)
      setMessage('✗ Failed to save')
    } finally {
      setSaving(false)
    }
  }

  const handleChange = (key: keyof Settings, value: any) => {
    if (settings) {
      setSettings({ ...settings, [key]: value })
    }
  }

  if (loading) return <div className="p-4">Loading...</div>
  if (!settings) return <div className="p-4">Failed to load settings</div>

  return (
    <div className="py-8 max-w-2xl">
      <h1 className="text-3xl font-bold mb-8">Settings</h1>

      <div className="bg-slate-900 p-6 rounded-lg border border-slate-800 space-y-6">
        {/* Wake up time */}
        <div>
          <label className="block text-sm font-semibold mb-2">Wake-up Time</label>
          <input
            type="time"
            value={settings.wake_up_time}
            onChange={(e) => handleChange('wake_up_time', e.target.value)}
            className="w-full bg-slate-800 border border-slate-700 rounded px-3 py-2"
          />
        </div>

        {/* Workout */}
        <div className="border-t border-slate-700 pt-6">
          <h3 className="font-semibold mb-4">Workout Preferences</h3>
          <div className="space-y-3">
            <div>
              <label className="block text-sm font-semibold mb-2">Duration (minutes)</label>
              <input
                type="number"
                value={settings.workout_duration_minutes}
                onChange={(e) => handleChange('workout_duration_minutes', parseInt(e.target.value))}
                className="w-full bg-slate-800 border border-slate-700 rounded px-3 py-2"
              />
            </div>
            <div>
              <label className="block text-sm font-semibold mb-2">Preferred Time</label>
              <select
                value={settings.workout_preference}
                onChange={(e) => handleChange('workout_preference', e.target.value)}
                className="w-full bg-slate-800 border border-slate-700 rounded px-3 py-2"
              >
                <option value="morning">Morning</option>
                <option value="evening">Evening</option>
                <option value="flexible">Flexible</option>
              </select>
            </div>
          </div>
        </div>

        {/* Commute */}
        <div className="border-t border-slate-700 pt-6">
          <label className="block text-sm font-semibold mb-2">Commute Buffer (minutes)</label>
          <input
            type="number"
            value={settings.commute_buffer_minutes}
            onChange={(e) => handleChange('commute_buffer_minutes', parseInt(e.target.value))}
            className="w-full bg-slate-800 border border-slate-700 rounded px-3 py-2"
          />
        </div>

        {/* Messaging */}
        <div className="border-t border-slate-700 pt-6">
          <label className="block text-sm font-semibold mb-2">Preferred Messaging</label>
          <select
            value={settings.preferred_messaging_channel}
            onChange={(e) => handleChange('preferred_messaging_channel', e.target.value)}
            className="w-full bg-slate-800 border border-slate-700 rounded px-3 py-2"
          >
            <option value="imessage">iMessage</option>
            <option value="twilio">SMS (Twilio)</option>
          </select>
        </div>

        {/* Calendar integrations */}
        <div className="border-t border-slate-700 pt-6">
          <h3 className="font-semibold mb-4">Calendar Integrations</h3>
          <div className="space-y-3">
            <label className="flex items-center gap-3">
              <input
                type="checkbox"
                checked={settings.google_calendar_enabled}
                onChange={(e) => handleChange('google_calendar_enabled', e.target.checked)}
                className="w-4 h-4"
              />
              <span>Google Calendar</span>
            </label>
            <label className="flex items-center gap-3">
              <input
                type="checkbox"
                checked={settings.apple_ical_enabled}
                onChange={(e) => handleChange('apple_ical_enabled', e.target.checked)}
                className="w-4 h-4"
              />
              <span>Apple iCal</span>
            </label>
          </div>
        </div>

        {/* Save button */}
        <div className="border-t border-slate-700 pt-6 flex gap-3">
          <button
            onClick={handleSave}
            disabled={saving}
            className="bg-blue-600 hover:bg-blue-700 disabled:bg-slate-700 text-white px-4 py-2 rounded font-semibold"
          >
            {saving ? 'Saving...' : 'Save Settings'}
          </button>
          {message && (
            <span className={message.includes('✓') ? 'text-green-400' : 'text-red-400'}>
              {message}
            </span>
          )}
        </div>
      </div>
    </div>
  )
}
