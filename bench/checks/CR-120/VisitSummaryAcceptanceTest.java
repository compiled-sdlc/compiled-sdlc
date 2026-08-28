package org.springframework.samples.petclinic.visits.web;

import java.text.SimpleDateFormat;
import java.util.Collection;
import java.util.Date;
import java.util.List;

import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.webmvc.test.autoconfigure.WebMvcTest;
import org.springframework.samples.petclinic.visits.model.Visit;
import org.springframework.samples.petclinic.visits.model.VisitRepository;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.web.servlet.MockMvc;

import static org.assertj.core.api.Assertions.assertThat;
import static org.hamcrest.Matchers.nullValue;
import static org.mockito.ArgumentMatchers.anyCollection;
import static org.mockito.BDDMockito.given;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * Acceptance check for CR-120, visits side: one summary for every pet asked about, in
 * the order they were asked for, from a single read.
 *
 * The whole web layer is loaded rather than one named class, so it does not matter
 * which class the summary is added to.
 */
@WebMvcTest
@ActiveProfiles("test")
class VisitSummaryAcceptanceTest {

    @Autowired
    MockMvc mvc;

    @MockitoBean
    VisitRepository visitRepository;

    private Date day(String date) throws Exception {
        return new SimpleDateFormat("yyyy-MM-dd").parse(date);
    }

    private Visit aVisit(int id, int petId, String date) throws Exception {
        return Visit.VisitBuilder.aVisit().id(id).petId(petId).date(day(date)).build();
    }

    private void givenTheVisitsOnRecord() throws Exception {
        given(visitRepository.findByPetIdIn(anyCollection())).willReturn(List.of(
            aVisit(1, 7, "2013-01-01"),
            aVisit(4, 7, "2013-01-04"),
            aVisit(2, 8, "2013-01-02")));
    }

    @Test
    void shouldSummariseEveryPetAskedAboutInTheOrderAsked() throws Exception {
        givenTheVisitsOnRecord();

        mvc.perform(get("/pets/visits/summary?petId=7,9,8"))
            .andExpect(status().isOk())
            .andExpect(jsonPath("$.summaries.length()").value(3))
            .andExpect(jsonPath("$.summaries[0].petId").value(7))
            .andExpect(jsonPath("$.summaries[1].petId").value(9))
            .andExpect(jsonPath("$.summaries[2].petId").value(8));
    }

    @Test
    void shouldCountTheVisitsAndDateTheMostRecent() throws Exception {
        givenTheVisitsOnRecord();

        mvc.perform(get("/pets/visits/summary?petId=7,8"))
            .andExpect(status().isOk())
            .andExpect(jsonPath("$.summaries[0].visitCount").value(2))
            .andExpect(jsonPath("$.summaries[0].lastVisitDate").value("2013-01-04"))
            .andExpect(jsonPath("$.summaries[1].visitCount").value(1))
            .andExpect(jsonPath("$.summaries[1].lastVisitDate").value("2013-01-02"));
    }

    @Test
    void shouldSummariseAPetWithNothingAsAZeroRatherThanLeaveItOut() throws Exception {
        givenTheVisitsOnRecord();

        mvc.perform(get("/pets/visits/summary?petId=9"))
            .andExpect(status().isOk())
            .andExpect(jsonPath("$.summaries.length()").value(1))
            .andExpect(jsonPath("$.summaries[0].petId").value(9))
            .andExpect(jsonPath("$.summaries[0].visitCount").value(0))
            .andExpect(jsonPath("$.summaries[0].lastVisitDate").value(nullValue()));
    }

    @Test
    @SuppressWarnings("unchecked")
    void shouldReadTheVisitsOnceForTheWholeBatch() throws Exception {
        givenTheVisitsOnRecord();

        mvc.perform(get("/pets/visits/summary?petId=7,9,8"))
            .andExpect(status().isOk());

        ArgumentCaptor<Collection<Integer>> captor = ArgumentCaptor.forClass(Collection.class);
        verify(visitRepository, times(1)).findByPetIdIn(captor.capture());
        assertThat(captor.getValue()).contains(7, 8, 9);
    }

    @Test
    void shouldLeaveTheBatchLookupItAlreadyHadAlone() throws Exception {
        givenTheVisitsOnRecord();

        mvc.perform(get("/pets/visits?petId=7,8"))
            .andExpect(status().isOk())
            .andExpect(jsonPath("$.items.length()").value(3))
            .andExpect(jsonPath("$.items[0].id").value(1));
    }
}
