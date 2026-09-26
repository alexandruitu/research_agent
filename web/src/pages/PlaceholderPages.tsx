const page = (title: string) => () => (
  <section>
    <h1>{title}</h1>
  </section>
);

export const RunsPage = page("Runs");
export const EvalsPage = page("Evals");
export const SystemMapPage = page("System map");
export const UsersPage = page("Users");
