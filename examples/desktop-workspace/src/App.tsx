import WorkspaceView from "./WorkspaceView";
import { useDemo } from "./useDemo";
import DemoDialogs from "./DemoDialogs";

export default function App() {
  const demo = useDemo();
  return (
    <>
      <WorkspaceView demo={demo} />
      <DemoDialogs demo={demo} />
    </>
  );
}
