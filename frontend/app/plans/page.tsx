'use client'

import { useEffect, useState } from 'react'
import { fetchPlans } from '@/lib/api'
import { format } from 'date-fns'

const USER_ID = 'test-user-1'

interface Plan {
  id: string
  run_id: string
  plan_date: string
  calendar_summary: string
  weather_summary: string
  commute_summary: string
  status: string
  created_at: string
}

export default function Plans() {
  const [plans, setPlans] = useState<Plan[]>([])
  const [loading, setLoading] = useState(true)
  const [selectedPlan, setSelectedPlan] = useState<Plan | null>(null)

  useEffect(() => {
    fetchData()
  }, [])

  const fetchData = async () => {
    try {
      const result = await fetchPlans(USER_ID)
      setPlans(result.plans || [])
    } catch (err) {
      console.error('Failed to fetch plans:', err)
    } finally {
      setLoading(false)
    }
  }

  if (loading) return <div className="p-4">Loading...</div>

  return (
    <div className="py-8">
      <h1 className="text-3xl font-bold mb-8">Daily Plans</h1>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {/* Plans List */}
        <div className="lg:col-span-1">
          <div className="bg-slate-900 rounded-lg border border-slate-800 max-h-96 overflow-y-auto">
            {plans.length === 0 ? (
              <p className="p-4 text-slate-400">No plans yet</p>
            ) : (
              plans.map((plan) => (
                <button
                  key={plan.id}
                  onClick={() => setSelectedPlan(plan)}
                  className={`w-full text-left p-4 border-b border-slate-700 hover:bg-slate-800 transition ${
                    selectedPlan?.id === plan.id ? 'bg-slate-800' : ''
                  }`}
                >
                  <div className="text-sm">
                    <div className="font-semibold">{plan.plan_date}</div>
                    <div className="text-slate-400">{plan.run_id.slice(0, 8)}...</div>
                    <div className={`text-xs mt-1 ${
                      plan.status === 'completed' ? 'text-green-400' : 'text-yellow-400'
                    }`}>
                      {plan.status}
                    </div>
                  </div>
                </button>
              ))
            )}
          </div>
        </div>

        {/* Plan Details */}
        <div className="lg:col-span-2">
          {selectedPlan ? (
            <div className="bg-slate-900 p-6 rounded-lg border border-slate-800 space-y-4">
              <div>
                <h2 className="text-lg font-semibold mb-2">Plan for {selectedPlan.plan_date}</h2>
                <p className="text-sm text-slate-400">Run ID: {selectedPlan.run_id}</p>
              </div>

              <div className="border-t border-slate-700 pt-4">
                <h3 className="font-semibold mb-2">Calendar</h3>
                <p className="text-sm text-slate-300">{selectedPlan.calendar_summary}</p>
              </div>

              <div className="border-t border-slate-700 pt-4">
                <h3 className="font-semibold mb-2">Weather</h3>
                <p className="text-sm text-slate-300">{selectedPlan.weather_summary}</p>
              </div>

              <div className="border-t border-slate-700 pt-4">
                <h3 className="font-semibold mb-2">Commute</h3>
                <p className="text-sm text-slate-300">{selectedPlan.commute_summary}</p>
              </div>

              <div className="border-t border-slate-700 pt-4">
                <h3 className="font-semibold mb-2">Metadata</h3>
                <p className="text-xs text-slate-400">
                  Created: {format(new Date(selectedPlan.created_at), 'PPpp')}
                </p>
              </div>
            </div>
          ) : (
            <div className="bg-slate-900 p-6 rounded-lg border border-slate-800 text-slate-400">
              Select a plan to view details
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
