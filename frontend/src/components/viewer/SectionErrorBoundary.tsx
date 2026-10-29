import React from 'react'
import { Html } from '@react-three/drei'
import { AlertTriangle, RotateCcw } from 'lucide-react'

interface SectionErrorBoundaryProps {
  children: React.ReactNode
  onReset: () => void
}

interface SectionErrorBoundaryState {
  hasError: boolean
  error: Error | null
}

export class SectionErrorBoundary extends React.Component<
  SectionErrorBoundaryProps,
  SectionErrorBoundaryState
> {
  constructor(props: SectionErrorBoundaryProps) {
    super(props)
    this.state = { hasError: false, error: null }
  }

  static getDerivedStateFromError(error: Error): SectionErrorBoundaryState {
    return { hasError: true, error }
  }

  componentDidCatch(error: Error, errorInfo: React.ErrorInfo) {
    console.error('[SectionErrorBoundary] Caught rendering error in sectioning:', error, errorInfo)
  }

  handleReset = () => {
    this.setState({ hasError: false, error: null })
    this.props.onReset()
  }

  render() {
    if (this.state.hasError) {
      return (
        <Html center style={{ pointerEvents: 'auto', zIndex: 100 }}>
          <div
            data-testid="section-error-boundary"
            className="p-4 bg-slate-900/95 border border-red-500/80 rounded-xl shadow-2xl backdrop-blur-md flex flex-col items-center gap-2 max-w-sm text-center text-xs select-none"
          >
            <div className="flex items-center gap-2 text-red-400 font-bold text-sm">
              <AlertTriangle className="w-4 h-4 text-red-400" />
              <span>Section View Error</span>
            </div>
            <p className="text-slate-300 text-[11px] leading-relaxed">
              {this.state.error?.message || 'A cutting plane rendering error occurred.'}
            </p>
            <button
              onClick={this.handleReset}
              data-testid="section-error-reset-btn"
              className="mt-1 flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-blue-600 hover:bg-blue-500 text-white font-semibold transition-colors shadow-sm"
            >
              <RotateCcw className="w-3.5 h-3.5" />
              <span>Reset Section Plane</span>
            </button>
          </div>
        </Html>
      )
    }

    return this.props.children
  }
}

export default SectionErrorBoundary
