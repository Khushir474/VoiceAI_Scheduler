'use client'

import { useEffect, useState } from 'react'
import { getOverview, triggerTestRun } from '@/lib/api'

const USER_ID = 'test-user-1'

interface Plan {
  id: string
  status: string
  calendar_summary: string
  weather_summary: string
}

interface Call {
  id: string
  status: string
  duration_seconds: number
}

interface Evaluation {
  overall_score: number
}

export default function Overview() {
  const [data, setData] = useState<any>(null)
  const [loading, setLoading] = useState(true)
  const [testRunning, setTestRunning] = useState(false)

  useEffect(() => {
    fetchData()
  }, [])

  const fetchData = async () => {
    try {
      const result = await getOverview(USER_ID)
      setData(result)
    } catch (err) {
      console.error('Failed to fetch overview:', err)
    } finally {
      setLoading(false)
    }
  }

  const handleTestRun = async () => {
    setTestRunning(true)
    try {
      const result = await triggerTestRun(USER_ID)
      console.log('Test run result:', result)
      await new Promise(resolve => setTimeout(resolve, 2000))
      await fetchData()
    } catch (err) {
      console.error('Test run failed:', err)
    } finally {
      setTestRunning(false)
    }
  }

  if (loading) return <div className="p-4">Loading...</div>

  return (
    <div className="py-8">
      <h1 className="text-3xl font-bold mb-8">Overview</h1>

      <button
        onClick={handleTestRun}
        disabled={testRunning}
        className="bg-blue-600 hover:bg-blue-700 disabled:bg-slate-700 text-white px-4 py-2 rounded mb-8"
      >
        {testRunning ? 'Running...' : 'Trigger Test Run'}
      </button>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {/* Latest Plan */}
        <div className="bg-slate-900 p-6 rounded-lg border border-slate-800">
          <h2 className="text-lg font-semibold mb-4">Latest Plan</h2>
          {data?.latest_plan ? (
            <div className="space-y-2 text-sm">
              <div>
                <span className="text-slate-400">Status:</span>{' '}
                <span className={`font-semibold ${data.latest_plan.status === 'completed' ? 'text-green-400' : 'text-yellow-400'}`}>
                  {data.latest_plan.status}
                </span>
              </div>
              <div>
                <span className="text-slate-400">Calendar:</span>{' '}
                <span className="truncate">{data.latest_plan.calendar_summary}</span>
              </div>
              <div>
                <span className="text-slate-400">Weather:</span>{' '}
                <span className="truncate">{data.latest_plan.weather_summary}</span>
              </div>
            </div>
          ) : (
            <p className="text-slate-400">No plan yet</p>
          )}
        </div>

        {/* Latest Call */}
        <div className="bg-slate-900 p-6 rounded-lg border border-slate-800">
          <h2 className="text-lg font-semibold mb-4">Latest Call</h2>
          {data?.latest_call ? (
            <div className="space-y-2 text-sm">
              <div>
                <span className="text-slate-400">Status:</span>{' '}
                <span className="font-semibold">{data.latest_call.status}</span>
              </div>
              <div>
                <span className="text-slate-400">Duration:</span>{' '}
                <span>{data.latest_call.duration_seconds || 'N/A'}s</span>
              </div>
            </div>
          ) : (
            <p className="text-slate-400">No calls yet</p>
          )}
        </div>

        {/* Evaluation */}
        <div className="bg-slate-900 p-6 rounded-lg border border-slate-800">
          <h2 className="text-lg font-semibold mb-4">Evaluation Score</h2>
          {data?.latest_evaluation ? (
            <div className="space-y-2">
              <div className="text-3xl font-bold">
                {(data.latest_evaluation.overall_score * 100).toFixed(0)}%
              </div>
              <p className="text-slate-400 text-sm">
                Usefulness & correctness score
              </p>
            </div>
          ) : (
            <p className="text-slate-400">No evaluation yet</p>
          )}
        </div>
      </div>
    </div>
  )
}
