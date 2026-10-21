import { Component, ErrorInfo, ReactNode } from 'react'
import { AlertTriangle, RefreshCw } from 'lucide-react'

interface Props {
  children: ReactNode
  fallbackTitle?: string
}

interface State {
  hasError: boolean
  error: Error | null
  errorInfo: ErrorInfo | null
}

export class ErrorBoundary extends Component<Props, State> {
  public state: State = {
    hasError: false,
    error: null,
    errorInfo: null,
  }

  public static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error, errorInfo: null }
  }

  public componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    console.error('ErrorBoundary caught an unhandled error:', error, errorInfo)
    this.setState({ errorInfo })
  }

  public handleReset = () => {
    this.setState({ hasError: false, error: null, errorInfo: null })
    window.location.reload()
  }

  public render() {
    if (this.state.hasError) {
      return (
        <div className="w-full h-full min-h-[300px] flex flex-col items-center justify-center p-8 bg-slate-950 text-slate-100">
          <div className="max-w-md w-full bg-slate-900 border border-red-500/40 rounded-xl p-6 shadow-2xl flex flex-col items-center text-center">
            <div className="w-12 h-12 rounded-full bg-red-500/20 border border-red-500/40 flex items-center justify-center mb-4 text-red-400">
              <AlertTriangle className="w-6 h-6" />
            </div>
            <h2 className="text-base font-semibold text-white mb-1">
              {this.props.fallbackTitle || 'Rendering Error in CAD System'}
            </h2>
            <p className="text-xs text-slate-400 mb-4">
              An unexpected error occurred while rendering the CAD interface. Details are captured below:
            </p>
            <div className="w-full bg-slate-950/80 border border-slate-800 rounded p-3 text-left mb-4 overflow-x-auto">
              <p className="text-xs font-mono text-red-300 break-words">
                {this.state.error?.message || 'Unknown runtime error'}
              </p>
            </div>
            <button
              onClick={this.handleReset}
              className="flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-500 text-white text-xs font-medium rounded-lg transition-colors shadow-md"
            >
              <RefreshCw className="w-3.5 h-3.5" />
              Reload Application
            </button>
          </div>
        </div>
      )
    }

    return this.props.children
  }
}
