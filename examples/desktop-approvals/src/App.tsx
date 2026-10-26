import ApprovalsView from "./ApprovalsView";
import { useDemo } from "./useDemo";
import DemoDialogs from "./DemoDialogs";

export default function App() {
  const demo = useDemo();
  return (
    <>
      <ApprovalsView demo={demo} />
      <DemoDialogs demo={demo} />
      {demo.notice && (
        <div className="demo-toast" role="status">
          <span>{demo.notice}</span>
          <button type="button" onClick={demo.dismissNotice} aria-label="关闭提示">关闭</button>
        </div>
      )}
    </>
  );
}
