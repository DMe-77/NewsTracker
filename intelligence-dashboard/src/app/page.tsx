import { getDashboardData } from "@/lib/dashboard-data";
import DashboardView from "./ui/dashboard-view";

export default async function Home() {
  const data = await getDashboardData();
  return <DashboardView data={data} />;
}
