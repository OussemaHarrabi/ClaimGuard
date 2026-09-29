import { ClinicPortal } from "../../../components/clinic-portal";

export default async function WorkspacePage({ params }: { params: Promise<{ page: string }> }) {
  const { page } = await params;
  return <ClinicPortal page={page} />;
}
