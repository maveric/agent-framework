import { BrowserRouter as Router, Routes, Route, Navigate } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { Layout } from './components/layout/Layout';
import { Dashboard } from './pages/Dashboard';
import { RunDetails } from './pages/RunDetails';
import { NewRun } from './pages/NewRun';
import { HumanQueue } from './pages/HumanQueue';

const queryClient = new QueryClient({
    defaultOptions: {
        queries: {
            refetchOnWindowFocus: false,
            retry: 1,
        },
    },
});

function App() {
    return (
        <QueryClientProvider client={queryClient}>
            <Router>
                <Routes>
                    <Route path="/" element={<Layout />}>
                        <Route index element={<Dashboard />} />
                        <Route path="new" element={<NewRun />} />
                        <Route path="runs" element={<Navigate to="/" replace />} />
                        <Route path="runs/:runId" element={<RunDetails />} />
                        <Route path="queue" element={<HumanQueue />} />
                        <Route path="*" element={<Navigate to="/" replace />} />
                    </Route>
                </Routes>
            </Router>
        </QueryClientProvider>
    );
}

export default App;
